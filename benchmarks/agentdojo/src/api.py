#!/usr/bin/env python3
import os
import sys
import shutil
import types
from pathlib import Path
from typing import Dict, Any, Optional, Sequence, cast
src_folder = Path(__file__).parent
sys.path.insert(0, str(src_folder))
from agentdojo.agent_pipeline.agent_pipeline import DEFENSES, AgentPipeline, PipelineConfig, get_llm
from agentdojo.agent_pipeline.ground_truth_pipeline import GroundTruthPipeline
from agentdojo.models import ModelsEnum
from agentdojo.task_suite.task_suite import functions_stack_trace_from_messages, model_output_from_messages, get_text_content_as_str
from agentdojo.base_tasks import BaseInjectionTask, BaseUserTask, Env


from agentdojo.task_suite.load_suites import get_suite
from agentdojo.scripts.benchmark import benchmark_suite_with_injections
from agentdojo.attacks.attack_registry import ATTACKS
from agentdojo.functions_runtime import FunctionCall
from agentdojo.logging import OutputLogger
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.types import ChatMessage, ChatUserMessage, MessageContentBlock, ChatAssistantMessage, ChatToolResultMessage
from agentdojo.logging import OutputLogger
from agentdojo.benchmark import run_task_with_injection_tasks
from agentdojo.agent_pipeline.errors import AbortAgentError
from benchmarks.agentdojo.src.agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
import json
import hashlib
import tempfile
from copy import deepcopy
from typing import Tuple, Sequence
from pydantic import BaseModel as _PydanticBaseModel

_INIT_CHAT_CACHE_DIR = Path(".cache/init_chat")


def _make_json_serializable(obj):
    """Recursively convert an object tree so it is fully JSON-serializable.

    Handles Pydantic BaseModel instances (via .model_dump()), dicts, lists,
    tuples, and primitive types.  Anything else is stringified as a fallback.
    """
    if isinstance(obj, _PydanticBaseModel):
        return _make_json_serializable(obj.model_dump())
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)



class AgentDojoChatSession:
    # Class-level in-memory cache (fast path for same-process hits).
    # Disk cache in _INIT_CHAT_CACHE_DIR provides persistence across runs.
    _init_chat_cache: dict = {}

    def __init__(
        self,
        suite_name: str,
        user_task_id: str,
        model_name: str,
        injection_task_name: str = "injection_task_0",
        run_dir: Path | str = "runs",
        defense_name: Optional[str] = None,
        system_message_name: Optional[str] = None
    ):
        """
        Initialize a multi‐turn session for agentdojo.

        - suite_name:     e.g. "slack"
        - user_task_id:   e.g. "user_task_1"
        - model_name:     e.g. "gpt-4o-2024-05-13"
        - attack_name:    e.g. "tool_knowledge" (or None)
        - defense_name:   optional defense
        - run_dir:        path under which logs will be written
        """
        # 1) Load suite & user task
        self.suite = get_suite("v1", suite_name)
        self.suite_name = suite_name
        self.user_task = self.suite.get_user_task_by_id(user_task_id)
        self.injection_task_name = injection_task_name
        self.inj_task = self.suite.get_injection_task_by_id(injection_task_name)
        self.defense_name = defense_name
        self.system_message_name = system_message_name
        self.model_name = model_name
            
        # self.defense_name = "repeat_user_prompt"

        # 2) Build a an OpenAI pipeline
        self.pipeline = AgentPipeline.from_config(
            PipelineConfig(
                llm=ModelsEnum(model_name),
                defense=self.defense_name,
                system_message_name=system_message_name,
                system_message=None,
                tool_output_format='json',
                )
        )
        self.pipeline.name = model_name

        # 3) Prepare environment & runtime
        env = self.suite.load_and_inject_default_environment({})
        self.task_env = self.user_task.init_environment(env)
        self.runtime = FunctionsRuntime(self.suite.tools)
        self.pre_environment = self.task_env.model_copy(deep=True)


        # 4) Instantiate attack object if provided
        from agentdojo.attacks.attack_registry import ATTACKS

        # 5) History buffer
        self.history: list[ChatMessage] = []
        self._injection_candidates: list[str] | None = None

        # 6) Where logs go (so TraceLogger can write)
        self.run_dir = Path(run_dir) / model_name / suite_name
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def _strip_spotlighting_delimiters(self, messages):
        """Remove spotlighting << >> delimiters from tool result messages."""
        if self.defense_name != "spotlighting_with_delimiting":
            return messages
        for msg in messages:
            if msg.get("role") == "tool" and msg.get("content"):
                for block in msg["content"]:
                    text = block.get("content", "")
                    if block.get("type") == "text" and text.startswith("<<") and text.endswith(">>"):
                        block["content"] = text[2:-2]
        return messages

    def _get_cache_key(self):
        """Cache key: init_chat output is unique per (suite, user_task, model, defense)."""
        return (self.suite_name, self.user_task.ID, self.model_name, self.defense_name)

    def _get_cache_filepath(self):
        """Return a deterministic file path for this cache key."""
        key = self._get_cache_key()
        key_str = json.dumps(list(key))
        key_hash = hashlib.sha256(key_str.encode()).hexdigest()[:16]
        # Human-readable prefix + short hash to avoid collisions
        defense_tag = key[3] or "none"
        safe_name = f"{key[0]}_{key[1]}_{key[2]}_{defense_tag}_{key_hash}"
        safe_name = safe_name.replace("/", "_").replace(" ", "_")
        return _INIT_CHAT_CACHE_DIR / f"{safe_name}.json"

    def init_chat(self) -> list[ChatMessage] | Sequence[ChatMessage]:
        """
        Send a user message and return the new assistant/tool messages.
        History is preserved.  Results are cached in-memory (fast, same-process)
        and on disk (persists across runs).  The API is only called on the
        very first invocation for a given (suite, user_task, model) triple.
        """
        cache_key = self._get_cache_key()

        # --- 1. In-memory cache (fastest) ---
        if cache_key in AgentDojoChatSession._init_chat_cache:
            cached = AgentDojoChatSession._init_chat_cache[cache_key]
            self.history = deepcopy(cached['history'])
            print("[init_chat] Returning in-memory cached result (no API call).")
            return deepcopy(cached['result'])

        # --- 2. Disk cache (cross-process, cross-run) ---
        cache_path = self._get_cache_filepath()
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                history = cached_data['history']
                result = cached_data['result']
                # Populate in-memory cache too
                AgentDojoChatSession._init_chat_cache[cache_key] = {
                    'history': deepcopy(history),
                    'result': deepcopy(result),
                }
                self.history = history
                print(f"[init_chat] Loaded from disk cache: {cache_path.name} (no API call).")
                return result
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"[init_chat] Disk cache invalid ({e}), re-fetching...")

        # --- 3. Cache miss — make the API call ---
        import time
        self.history = []
        message = self.user_task.PROMPT


        user_message: ChatUserMessage = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "content": message
                }
            ]
        }

        # Append the user message to history
        if not len(self.history) == 0:
            self.history.append(user_message)

        # Query the pipeline
        new_messages = []
        _, _, self.task_env, new_messages, _ = self.pipeline.query(
            message, self.runtime, self.task_env, self.history
        )

        self._strip_spotlighting_delimiters(new_messages)
        self.history = new_messages
        result = list(new_messages[1:])

        # Populate in-memory cache
        AgentDojoChatSession._init_chat_cache[cache_key] = {
            'history': deepcopy(self.history),
            'result': deepcopy(result),
        }

        # Persist to disk (serialize Pydantic models, write atomically)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                'cache_key': list(cache_key),
                'history': _make_json_serializable(self.history),
                'result': _make_json_serializable(result),
            }
            # Serialize to string first so a TypeError won't leave a partial file
            json_str = json.dumps(payload, indent=2)
            # Atomic write: temp file + rename
            fd, tmp_path = tempfile.mkstemp(
                dir=str(cache_path.parent), suffix='.tmp'
            )
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(json_str)
                os.replace(tmp_path, str(cache_path))
            except BaseException:
                os.unlink(tmp_path)
                raise
            print(f"[init_chat] Result cached to disk: {cache_path.name}")
        except (TypeError, OSError) as e:
            print(f"[init_chat] Could not write disk cache ({e}), in-memory only.")

        return result

    def send(self, message: str | None) -> tuple[list[ChatMessage] | Sequence[ChatMessage], bool, bool]:
        """
        Send a user message and return the new assistant/tool messages.
        History is preserved.
        """
        # Build a single‐turn prompt from the latest user message
        # and then call pipeline.query
        import time
        if message is None:
            message = self.user_task.PROMPT


        user_message: ChatUserMessage = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "content": message
                }
            ]
        }

        # Append the user message to history
        if not len(self.history) == 0:
            self.history.append(user_message)

        # Query the pipeline
        new_messages = []
        for _ in range(3):
            try:
                _, _, self.task_env, new_messages, _ = self.pipeline.query(
                    message, self.runtime, self.task_env, self.history
                )
            except AbortAgentError as e:
                self.task_env = e.task_environment
                new_messages = e.messages

            # Stop once we get at least one assistant message
            if any(m["role"] == "assistant" for m in new_messages):
                break

        if not new_messages:
            raise RuntimeError("No assistant response after 3 tries")
        
        # Append only the new messages to history
        for msg in new_messages:
            if msg not in self.history:
                self.history.append(msg)

        # Check utility and security
        user_task = self.user_task
        post_environment = self.task_env
        model_output=model_output_from_messages(new_messages)
        functions = functions_stack_trace_from_messages(new_messages)

        utility = _check_user_task_utility(
            user_task,
            model_output or [],
            self.pre_environment,
            post_environment,  # type: ignore
            functions,
        )

        orig_injection: BaseInjectionTask = self.suite.get_injection_task_by_id(self.injection_id)


        security = _check_injection_task_security(
            orig_injection,
            model_output or [],
            self.pre_environment,
            post_environment,  # type: ignore
            functions,
        )

        print(f"\nUtility (so far): {utility} \nSecurity (so far): {security}")



        return new_messages,  utility, security

    

    def prompt_agent(
        self, content: str
    ) -> str:
        """
        Replace history[index] with the ChatMessage described by json_str,
        drop all subsequent messages, then resume the session from the
        last message (tool, assistant, user, or system).
        """
        if len(self.history) == 0:
            self.init_chat()
        
        msg_to_change = self.history[1]
        msg_to_change['content'][0] = {'type':'text', 'content': content}
        self.history = self.history[:2]

        # 4) Build prompt from the last message (any role)
        last = self.history[-1]
        prompt = ""
        if blocks := last.get("content"):
            prompt = get_text_content_as_str(blocks)

        # 5) Continue the conversation
        new_messages: Sequence[ChatMessage] = []
        for _ in range(3):
            try:
                _, _, self.task_env, new_messages, _ = self.pipeline.query(
                    prompt, self.runtime, self.task_env, self.history
                )
            except AbortAgentError as e:
                self.task_env = e.task_environment
                new_messages = e.messages
            if any(m["role"] == "assistant" for m in new_messages):
                break
        if not new_messages:
            raise RuntimeError("No assistant response after 3 tries")
        if last.get("role") != "user" and new_messages[1].get("role") == "user":
            new_messages = list(new_messages)
            new_messages.remove(new_messages[1])
        
        # 6) Append only the new messages
        for m in new_messages:
            if m not in self.history:
                self.history.append(m)



        return self.history


    def inject_prompt_via_environment(
        self, content: str
    ) -> tuple[Sequence[ChatMessage], bool, bool]:
        """
        Inject content into the environment at the injection candidates that are
        visible to the model, then run the user task once.

        Returns:
            (messages, security, utility)
        """
        # Escape characters that would break YAML double-quoted strings.
        # The placeholders live inside double-quoted YAML values, so we must
        # keep the substituted text on a single logical YAML line.
        yaml_safe_content = (
            content
            .replace('\\', '\\\\')
            .replace('"', '\\"')
            .replace('\n', '\\n')
            .replace('\r', '\\r')
            .replace('\t', '\\t')
        )
        injections = {inj: yaml_safe_content for inj in self._get_injection_candidates()}

        environment = self.suite.load_and_inject_default_environment(injections)
        task_environment = self.user_task.init_environment(environment)
        pre_environment = task_environment.model_copy(deep=True)

        runtime = FunctionsRuntime(self.suite.tools)
        prompt = self.user_task.PROMPT
        messages: Sequence[ChatMessage] = []
        model_output = None
        for _ in range(3):
            try:
                _, _, task_environment, messages, _ = self.pipeline.query(
                    prompt, runtime, task_environment, []
                )
            except AbortAgentError as e:
                task_environment = e.task_environment
                messages = e.messages

            model_output = model_output_from_messages(messages)
            if model_output is not None:
                break

        if model_output is None:
            raise RuntimeError("Model output was None after 3 tries")

        functions_stack_trace = functions_stack_trace_from_messages(messages)
        utility = self.suite._check_user_task_utility(
            self.user_task,
            model_output or [],
            pre_environment,
            task_environment,  # type: ignore
            functions_stack_trace,
        )

        security = self.suite._check_injection_task_security(
            self.inj_task,
            model_output or [],
            pre_environment,
            task_environment,  # type: ignore
            functions_stack_trace,
        )

        self._strip_spotlighting_delimiters(messages)
        self.history = list(messages)
        return messages[1:], security, utility


    def inject_content_at_index_limited(
        self, content: str, index: int
    ) -> Sequence[ChatMessage]:
        """
        Replace history[index] with the ChatMessage described by json_str,
        drop all subsequent messages, then resume the session from the
        last message (tool, assistant, user, or system).
        """

        if not (0 <= index < len(self.history)):
            return f"ERROR: Index {index} out of range (0–{len(self.history)-1})", "", ""
        
        if self.history[index].get('role') in ['assistant', 'user', 'system']:
            return f"ERROR: Can't replace message with role: {self.history[index].get('role')}.", "", ""
        
        msg_to_change = self.history[index]
        benign_content = msg_to_change["content"][0]["content"]
        new_content =  content
        msg_to_change['content'][0] = {'type':'text', 'content': new_content}
        for i in range(index, len(self.history)):
            if self.history[i].get('role') == 'assistant':
                index = i - 1
                break

        self.history = self.history[: index + 1]

        last = self.history[-1]
        prompt = ""
        new_messages: Sequence[ChatMessage] = []
        # Implementing defenses and treating them
        if self.defense_name == 'repeat_user_prompt' and self.history[index].get('role') != 'user':
            prompt = self.user_task.PROMPT
            user_message: ChatUserMessage = {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "content": prompt
                    }
                ]
            }
            self.history.append(user_message)

        prompt, self.runtime, self.task_env, new_messages, extra = self.pipeline.elements[-2].query(
            prompt, self.runtime, self.task_env, self.history
        )
        prompt, runtime, self.task_env, new_messages, extra = self.pipeline.elements[-1].query(
            prompt, self.runtime, self.task_env, new_messages
        )

        print(new_messages)

        self.history = new_messages.copy()
        self.history[index]["content"][0]["content"] = benign_content


        security = self.suite._check_injection_task_security(self.inj_task, model_output_from_messages(new_messages), self.pre_environment, self.task_env, functions_stack_trace_from_messages(new_messages))

        success = f"################## PENTESTING GOAL ACHIEVED: {security} ################"


        utility_bool = self.suite._check_user_task_utility(self.user_task, model_output_from_messages(new_messages), self.pre_environment, self.task_env, functions_stack_trace_from_messages(new_messages))

        utility = f"################## UTILITY GOAL ACHIEVED: {utility_bool} ################"

        return new_messages[1:], success, utility


    def embed_payload_in_tool(
        self, content: str, index: int
    ) -> Sequence[ChatMessage]:
        """
        Replace history[index] with the ChatMessage described by json_str,
        drop all subsequent messages, then resume the session from the
        last message (tool, assistant, user, or system).
        """

        if not (0 <= index < len(self.history)):
            return f"ERROR: Index {index} out of range (0–{len(self.history)-1})", "", ""
        
        if self.history[index].get('role') in ['assistant', 'user', 'system']:
            return f"ERROR: Can't replace message with role: {self.history[index].get('role')}.", "", ""
        
        msg_to_change = self.history[index]
        benign_content = msg_to_change["content"][0]["content"]
        new_content =  benign_content + "\n\n" + content 
        msg_to_change['content'][0] = {'type':'text', 'content': new_content}
        for i in range(index, len(self.history)):
            if self.history[i].get('role') == 'assistant':
                index = i - 1
                break

        self.history = self.history[: index + 1]

        last = self.history[-1]
        prompt = ""
        new_messages: Sequence[ChatMessage] = []
        # Implementing defenses and treating them
        if self.defense_name == 'repeat_user_prompt' and self.history[index].get('role') != 'user':
            prompt = self.user_task.PROMPT
            user_message: ChatUserMessage = {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "content": prompt
                    }
                ]
            }
            self.history.append(user_message)

        prompt, self.runtime, self.task_env, new_messages, extra = self.pipeline.elements[-2].query(
            prompt, self.runtime, self.task_env, self.history
        )
        prompt, runtime, self.task_env, new_messages, extra = self.pipeline.elements[-1].query(
            prompt, self.runtime, self.task_env, new_messages
        )

        print(new_messages)

        self.history = new_messages.copy()
        self.history[index]["content"][0]["content"] = benign_content


        security = self.suite._check_injection_task_security(self.inj_task, model_output_from_messages(new_messages), self.pre_environment, self.task_env, functions_stack_trace_from_messages(new_messages))

        success = f"################## PENTESTING GOAL ACHIEVED: {security} ################"


        utility_bool = self.suite._check_user_task_utility(self.user_task, model_output_from_messages(new_messages), self.pre_environment, self.task_env, functions_stack_trace_from_messages(new_messages))

        utility = f"################## UTILITY GOAL ACHIEVED: {utility_bool} ################"

        return new_messages[1:], success, utility




    def get_history(self) -> list[ChatMessage]:
        """Return the full conversation history so far."""
        return self.history

    def _get_injection_candidates(self) -> list[str]:
        if self._injection_candidates is not None:
            return self._injection_candidates

        injection_defaults = self.suite.get_injection_vector_defaults()
        canary_injections = {inj: f"<CANARY---{inj}-->" for inj in injection_defaults}
        environment = self.suite.load_and_inject_default_environment(canary_injections)

        gt_pipeline = GroundTruthPipeline(self.user_task)
        runtime = FunctionsRuntime(self.suite.tools)
        _, _, _, responses, _ = gt_pipeline.query(self.user_task.PROMPT, runtime, environment)

        injection_candidates = []
        for inj in canary_injections:
            found = False
            for response in responses:
                if response.get("content") is None:
                    continue
                if canary_injections[inj] in get_text_content_as_str(response["content"]):
                    found = True
                    break
            if found:
                injection_candidates.append(inj)

        if not injection_candidates:
            raise ValueError(f"{self.user_task.ID} is not injectable.")

        self._injection_candidates = injection_candidates
        return injection_candidates

    def get_injected_tool_output_info(self) -> str:
        """
        Find which tool output(s) contain the injection location using canary strings.
        Returns the tool name and content with <<INJECTION_LOCATION>> markers.
        """
        injection_defaults = self.suite.get_injection_vector_defaults()
        canary_injections = {inj: f"<CANARY---{inj}-->" for inj in injection_defaults}
        environment = self.suite.load_and_inject_default_environment(canary_injections)

        gt_pipeline = GroundTruthPipeline(self.user_task)
        runtime = FunctionsRuntime(self.suite.tools)
        _, _, _, responses, _ = gt_pipeline.query(self.user_task.PROMPT, runtime, environment)

        results = []
        for response in responses:
            if response.get("role") != "tool":
                continue
            content_blocks = response.get("content", [])
            if not content_blocks:
                continue
            text = get_text_content_as_str(content_blocks)

            has_canary = False
            marked_text = text
            for inj, canary in canary_injections.items():
                if canary in marked_text:
                    marked_text = marked_text.replace(canary, "<<INJECTION_LOCATION>>")
                    has_canary = True

            if has_canary:
                tool_call = response.get("tool_call")
                tool_name = tool_call.function if tool_call else "unknown"
                results.append(f"{tool_name} - '{marked_text}'")

        return "\n".join(results) if results else "No injection location found."

    def get_benign_response(self) -> str:
        """
        Run init_chat and return the last assistant message's text content.
        """
        messages = self.init_chat()
        # Walk backwards to find the last assistant message with text content
        for msg in reversed(list(messages)):
            if msg.get("role") == "assistant" and msg.get("content"):
                text = get_text_content_as_str(msg["content"])
                if text.strip():
                    return text
        return ""

    def get_agent_task(self) -> str:
        """
        Return the user's message to the agent (the task prompt at index 1).
        """
        if not self.history:
            self.init_chat()
        # history[0] = system, history[1] = user
        user_msg = self.history[1]
        return get_text_content_as_str(user_msg["content"])


############# UTIL ##################

def _check_user_task_utility(
    task: BaseUserTask,
    model_output: list[MessageContentBlock],
    pre_environment: Env,
    task_environment: Env,
    functions_stack_trace: Sequence[FunctionCall],
) -> bool:
    output_text_content = get_text_content_as_str(model_output)
    utility_from_stack_traces = task.utility_from_traces(
        output_text_content, pre_environment, task_environment, functions_stack_trace
    )
    if utility_from_stack_traces is not None:
        return utility_from_stack_traces
    return task.utility(output_text_content, pre_environment, task_environment)

def _check_injection_task_security(
    task: BaseInjectionTask,
    model_output: list[MessageContentBlock],
    pre_environment: Env,
    task_environment: Env,
    functions_stack_trace: Sequence[FunctionCall],
) -> bool:
    output_text_content = get_text_content_as_str(model_output)
    security_from_stack_traces = task.security_from_traces(
        output_text_content, pre_environment, task_environment, functions_stack_trace
    )
    if security_from_stack_traces is not None:
        return security_from_stack_traces
    return task.security(output_text_content, pre_environment, task_environment)


def get_injection_goal(suite, injection_id):
    suite = get_suite("v1", suite)
    # Find the injection *instance*
    orig_injection: BaseInjectionTask = suite.get_injection_task_by_id(injection_id)
    return orig_injection.GOAL


def get_user_task_prompt(suite, user_task_id):
    suite = get_suite("v1", suite)
    user_task = suite.get_user_task_by_id(user_task_id)
    return user_task.PROMPT