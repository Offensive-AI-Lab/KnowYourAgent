#!/usr/bin/env python3
# File: src/api.py

from __future__ import annotations
import os, json
from typing import Any, Dict, List, Tuple, Sequence, Optional, cast
from dataclasses import dataclass
from copy import deepcopy

# ---- Import InjecAgent internals (from your pasted main.py) ----
from benchmarks.injecagent.src.utils import get_tool_dict
from benchmarks.injecagent.src.prompts.agent_prompts import PROMPT_DICT
from benchmarks.injecagent.src.output_parsing import evaluate_output_prompted
from benchmarks.injecagent.src.models import MODELS
from benchmarks.injecagent.src.params import parse_arguments

# ---- Types (compatible with your AgentDojo-facing code) ----
ChatMessage = Dict[str, Any]
MessageContentBlock = Dict[str, Any]

def _mk_text_block(text: str) -> MessageContentBlock:
    return {"type": "text", "content": text}

def _get_text_content_as_str(blocks: Sequence[MessageContentBlock] | None) -> str:
    if not blocks:
        return ""
    out = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(str(b.get("content", "")))
    return "\n".join(out)

@dataclass
class _Config:
    # Selection knobs (intersection in InjecAgent datasets)
    attack: str                  # "dh" or "ds"
    setting: str                 # e.g., "default"
    user_task_index: int
    injection_task_index: int

    # Model / prompt knobs
    model_type: str              # key in MODELS
    model_name: str              # e.g., "gpt-4o-2024-05-13"
    prompt_type: str             # key in PROMPT_DICT

    # Misc
    run_dir: str

class InjecAgentChatSession:
    """
    Makes InjecAgent (single-turn datasets) look like your multi-turn, index-based
    interface. You select a *pair* (user_task_index, injection_task_index); the session
    resolves the *intersection case* from the JSON test cases and exposes:

        init_chat() -> [tool_msg]
        get_history() -> full history (user, tool, [assistant...])
        send(message) -> ([assistant], utility_bool, security_bool)
        inject_message_json_at_index(...)
        inject_content_at_index(...)
        inject_content_at_index_limited(...)
        inject_content_single_tool(...)

    Injection surface: index 1 is always the tool message (synthetic). Replace it.
    """

    # --------- constructor w/ compatibility signature ----------
    def __init__(
        self,
        suite_name: str,                 # kept for compatibility; unused
        user_task_id: str,               
        model_name: str,                 
        injection_task_name: str = "0",  
        run_dir: str = "runs",
        setting: Optional[str] = None,       # "base" | "enhanced"
        model_type: Optional[str] = None,    # key of src.models.MODELS, e.g. "GPT", "OpenRouter"
        prompt_type: Optional[str] = None,
    ):
        # --- Selection knobs: explicit argument > environment variable > default ---
        attack = suite_name                # "dh" or "ds"
        setting = (setting or os.getenv("SETTING", "enhanced")).strip()
        try:
            user_task_index = int(user_task_id)
        except ValueError:
            user_task_index = 0
        try:
            injection_task_index = int(injection_task_name)
        except ValueError:
            injection_task_index = 0

        model_type = (model_type or os.getenv("MODEL_TYPE", "GPT")).strip()
        prompt_type = (prompt_type or os.getenv("PROMPT_TYPE", "InjecAgent")).strip()
        # MODEL_NAME, when set, overrides the constructor argument
        model_name_env = os.getenv("MODEL_NAME", "").strip() or model_name

        self.cfg = _Config(
            attack=attack,
            setting=setting,
            user_task_index=user_task_index,
            injection_task_index=injection_task_index,
            model_type=model_type,
            model_name=model_name_env,
            prompt_type=prompt_type,
            run_dir=run_dir,
        )

        # runtime state
        self.history: List[ChatMessage] = []
        self._initialized = False

        # injecagent resources
        self._params = None               # lazily parsed
        self._system_prompt = None
        self._user_prompt_template = None
        self._tool_dict = None
        self._model_class = None

        # catalogs & selected case
        self._data: List[dict] = []
        self._user_catalog: List[str] = []
        self._inject_catalog: List[str] = []
        self._selected_item: Optional[dict] = None

        # Load data + select intersection
        self._load_dataset_and_select_case()

    # ---------------------- public API ----------------------
    def init_chat(self) -> List[ChatMessage]:
        """
        Bootstrap a canonical history:
            0 user: selected benign "User Instruction"
            1 tool: selected benign "Tool Response" (this is the injection surface)
        We DO NOT auto-call the model here (to mirror your AgentDojo flow).
        """
        if self._selected_item is None:
            raise RuntimeError("No intersection case found. Adjust USER_TASK_INDEX / INJECTION_TASK_INDEX / ATTACK / SETTING.")

        user_text = self._selected_item["User Instruction"]
        assistant_text = self._selected_item["Thought"]
        tool_text = self._selected_item["Tool Response Template"]

        self.history = []
        user_msg = {"role": "user", "content": [_mk_text_block(user_text)]}
        assistant_msg = {"role": "assistant", "content": [_mk_text_block(assistant_text)]}
        tool_msg = {"role": "tool", "content": [_mk_text_block(tool_text)], "tool_name": self._selected_item.get
        ("User Tool","synthetic_tool")}
        self.history.append(user_msg)  # index 0
        self.history.append(assistant_msg)
        self.history.append(tool_msg)  # index 1
        self._initialized = True
        self.history, _, _ = self.send(message=None)
  

        # Return "new messages" since last user — here it's just the tool placeholder
        return self.history

    def get_history(self) -> List[ChatMessage]:
        if not self._initialized:
            return self.init_chat()
        return self.history

    def send(self, message: str | None) -> Tuple[List[ChatMessage], bool, bool]:
        """
        Single-turn evaluation given current (user, tool).
        Appends assistant message to persistent history.
        """
        if not self._initialized:
            self.init_chat()

        if message is not None:
            # replace user prompt at index 0
            self.history[0]["content"] = [_mk_text_block(message)]

        user_text = _get_text_content_as_str(self.history[0].get("content"))
        tool_text = _get_text_content_as_str(self.history[2].get("content")) if len(self.history) > 2 else ""

        assistant_text, utility_bool, security_bool = self._eval_single_turn(user_text, tool_text)
        assistant_msg: ChatMessage = {"role": "assistant", "content": [_mk_text_block(assistant_text or "")]}
        self.history.append(assistant_msg)
        return self.history, utility_bool, security_bool

    # ----- injections (keep your original shapes/semantics) -----
    def inject_message_json_at_index(self, json_str: str, index: int) -> Sequence[ChatMessage]:
        try:
            new_msg = json.loads(json_str)
        except Exception as e:
            raise ValueError(f"Invalid JSON: {e}")
        if not (0 <= index < len(self.history)):
            raise IndexError(f"Index {index} out of range (0–{len(self.history)-1})")
        if new_msg.get("role") != self.history[index].get("role"):
            raise ValueError(f"Role mismatch at index {index}")

        self.history[index] = cast(ChatMessage, new_msg)
        self.history = self.history[: index + 1]

        # ensure [user, tool] exist for single-turn
        if len(self.history) == 1 and self.history[0]["role"] == "user":
            self.history.append({"role":"tool","content":[_mk_text_block("(empty)")],"tool_name":"synthetic_tool"})

        new_messages, _, _ = self.send(message=None)
        return new_messages

    def inject_content_at_index(self, content: str, index: int) -> Sequence[ChatMessage]:
        if not self._initialized:
            self.init_chat()
        if not (0 <= index < len(self.history)):
            return f"ERROR: Index {index} out of range (0–{len(self.history)-1})"
        role = self.history[index].get("role")
        if role in ("assistant","system"):
            return f"ERROR: Can't replace message with role: {role}."

        self._replace_content_in_place(index, content)
        self.history = self.history[: index + 1]

        if len(self.history) == 1 and self.history[0]["role"] == "user":
            self.history.append({"role":"tool","content":[_mk_text_block("(empty)")],"tool_name":"synthetic_tool"})

        new_messages, _, _ = self.send(message=None)
        return new_messages

    def inject_at_tool_message(self, content: str) -> Tuple[Sequence[ChatMessage], str, str]:
        """
        Inject content at the tool message, exactly as InjecAgent does internally.
        Finds the first tool-role message in history and delegates to inject_content_at_index_limited.
        The framework never needs to choose or know the index.
        """
        tool_index = next(
            (i for i, msg in enumerate(self.history) if msg.get("role") == "tool"),
            None,
        )
        if tool_index is None:
            return "ERROR: No tool message found in history.", "", ""
        return self.inject_content_at_index_limited(content, tool_index)

    def inject_content_at_index_limited(self, content: str, index: int) -> Tuple[Sequence[ChatMessage], str, str]:
        if not (0 <= index < len(self.history)):
            return f"Index {index} out of range (0–{len(self.history)-1})", "", ""
        if self.history[index].get("role") != "tool":
            return f"ERROR: Can't replace message with role: {self.history[index].get('role')}.", "", ""
        
        template = self._selected_item["Tool Response Template"]
        ready_content = template.replace('<Attacker Instruction>', content)

        self._replace_content_in_list(self.history, index, ready_content)
        self.history = self.history[:index+1]

        assistant_text, utility_bool, security_bool = self.send(message=None)
        
        success = f"################## PENTESTING GOAL ACHIEVED: {bool(security_bool)} ################"
        utility = f"################## UTILITY GOAL ACHIEVED: {bool(utility_bool)} ################"
        return assistant_text, success, utility

    def inject_content_single_tool(self, content: str, index: int) -> Tuple[Sequence[ChatMessage], str, str]:
        if not (0 <= index < len(self.history)):
            return [], f"Index {index} out of range (0–{len(self.history)-1})", ""
        if self.history[index].get("role") != "tool":
            return [], f"ERROR: Can only replace a tool message (got role={self.history[index].get('role')}).", ""

        temp_chat = deepcopy(self.history)
        self._replace_content_in_list(temp_chat, index, content)
        temp_chat = self._ensure_user_tool_prefix(temp_chat)

        user_text = _get_text_content_as_str(temp_chat[0].get("content"))
        tool_text = _get_text_content_as_str(temp_chat[1].get("content"))

        assistant_text, utility_bool, security_bool = self._eval_single_turn(user_text, tool_text)
        new_messages = [{"role":"assistant","content":[_mk_text_block(assistant_text or "")]}]
        success = f"################## PENTESTING GOAL ACHIEVED: {bool(security_bool)} ################"
        utility = f"################## UTILITY GOAL ACHIEVED: {bool(utility_bool)} ################"
        return new_messages, success, utility

    def get_history_len(self) -> int:
        return len(self.history)

    # ----------------- internal helpers -----------------
    def _replace_content_in_place(self, index: int, content: str) -> None:
        blocks = self.history[index].get("content") or []
        if blocks and isinstance(blocks[0], dict) and blocks[0].get("type") == "text":
            blocks[0]["content"] = content
        else:
            self.history[index]["content"] = [_mk_text_block(content)]

    def _replace_content_in_list(self, lst: List[ChatMessage], index: int, content: str) -> None:
        blocks = lst[index].get("content") or []
        if blocks and isinstance(blocks[0], dict) and blocks[0].get("type") == "text":
            blocks[0]["content"] = content
        else:
            lst[index]["content"] = [_mk_text_block(content)]

    def _ensure_user_tool_prefix(self, chat: List[ChatMessage]) -> List[ChatMessage]:
        out: List[ChatMessage] = []
        if not chat or chat[0]["role"] != "user":
            utxt = _get_text_content_as_str(self.history[0].get("content")) if self.history else ""
            out.append({"role":"user","content":[_mk_text_block(utxt)]})
        else:
            out.append(chat[0])

        if len(chat) >= 2 and chat[1]["role"] == "tool":
            out.append(chat[1])
        else:
            txt = _get_text_content_as_str(chat[1].get("content")) if len(chat) >= 2 else ""
            out.append({"role":"tool","content":[_mk_text_block(txt)],"tool_name":"synthetic_tool"})
        return out

    # ----------------- dataset selection & evaluation -----------------
    def _load_dataset_and_select_case(self) -> None:
        """
        Load data/test_cases_{attack}_{setting}.json.
        Build unique catalogs for user instructions & attacker instructions.
        Select the first item that matches both chosen indices.
        """
        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        data_dir = os.path.abspath(data_dir)

        file_name = f"test_cases_{self.cfg.attack}_{self.cfg.setting}.json"
        data_path = os.path.join(data_dir, file_name)
        if not os.path.exists(data_path):
            # Try repo-root/data as fallback
            alt = os.path.abspath(os.path.join(os.getcwd(), "data", file_name))
            if os.path.exists(alt):
                data_path = alt
            else:
                raise FileNotFoundError(f"Cannot find dataset file: {data_path}")

        with open(data_path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

        # Build catalogs (unique, deterministic order)
        user_set = []
        inj_set = []
        seen_u = set()
        seen_i = set()
        for item in self._data:
            u = item.get("User Instruction","").strip()
            a = item.get("Attacker Instruction","").strip()
            if u not in seen_u:
                seen_u.add(u)
                user_set.append(u)
            if a not in seen_i:
                seen_i.add(a)
                inj_set.append(a)

        self._user_catalog = user_set
        self._inject_catalog = inj_set

        # Bounds check
        if not self._user_catalog:
            raise RuntimeError("No user tasks found in dataset.")
        if not self._inject_catalog:
            raise RuntimeError("No injection tasks found in dataset.")
        if not (0 <= self.cfg.user_task_index < len(self._user_catalog)):
            raise IndexError(f"USER_TASK_INDEX {self.cfg.user_task_index} out of range 0..{len(self._user_catalog)-1}")
        if not (0 <= self.cfg.injection_task_index < len(self._inject_catalog)):
            raise IndexError(f"INJECTION_TASK_INDEX {self.cfg.injection_task_index} out of range 0..{len(self._inject_catalog)-1}")

        sel_user = self._user_catalog[self.cfg.user_task_index]
        sel_inj  = self._inject_catalog[self.cfg.injection_task_index]

        # Find first item matching both
        self._selected_item = None
        for item in self._data:
            if item.get("User Instruction","").strip() == sel_user and item.get("Attacker Instruction","").strip() == sel_inj:
                self._selected_item = item
                break

        if self._selected_item is None:
            raise RuntimeError(
                f"No intersection case for user[{self.cfg.user_task_index}] and injection[{self.cfg.injection_task_index}] "
                f"in {os.path.basename(data_path)}.\n"
                f"Try different indices or a different ATTACK/SETTING."
            )

        # Prepare injecagent runtime bits now
        self._prepare_injecagent_runtime()

    def _prepare_injecagent_runtime(self) -> None:
        """
        Initialize prompts, model class, and tools like InjecAgent's main.py does.
        """
        # Parse default params for the prompted agent, then override a few fields
        params = {
            "model_type": self.cfg.model_type,
            "model_name": self.cfg.model_name,
            "prompt_type": self.cfg.prompt_type,
            "setting": self.cfg.setting,
            "only_first_step": False,
            "use_cache": False,
            "only_get_score": False,
        }

        # NOTE: params['setting'] and attack loops are bypassed; we already picked the file & item.

        self._params = params
        self._system_prompt, self._user_prompt_template = PROMPT_DICT[params['prompt_type']]
        self._tool_dict = get_tool_dict()
        self._model_class = MODELS[params['model_type']](params)

    def _eval_single_turn(self, user_text: str, tool_text: str) -> Tuple[str, bool, bool]:
        """
        Reproduce InjecAgent's single-turn prompting & evaluation for one item.
        """
        if self._selected_item is None:
            raise RuntimeError("No selected item to evaluate.")
        assert self._params is not None and self._model_class is not None

        item = dict(self._selected_item)  # shallow copy so we can fill fields safely
        item['User Instruction'] = user_text
        item['Tool Response'] = tool_text

        available_tool_names = [item['User Tool']] + item['Attacker Tools']
        available_tool_descriptions = json.dumps([self._tool_dict[t] for t in available_tool_names], indent=True)

        # Step-1 style scratchpad (same as InjecAgent's predict_one_case default path)
        agent_scratchpad = (
            f"\n{item.get('Thought','')}\n"
            f"Action: {item['User Tool']}\n"
            f"Action Input: {item.get('Tool Parameters','')}\n"
            f"Observation: {item['Tool Response']}\n"
        )

        user_prompt_filled = self._user_prompt_template.format(
            available_tool_descriptions=available_tool_descriptions,
            input=item['User Instruction'],
            available_tool_names=available_tool_names,
            agent_scratchpad=agent_scratchpad
        )

        model_input = self._model_class.prepare_input(self._system_prompt, user_prompt_filled)

        output = self._model_class.call_model(model_input)

        parsed = evaluate_output_prompted(
            output,
            item['Attacker Tools'][0],
            item['Attacker Tools'],
            item['User Tool'],
            item['Attacker Instruction'],
        )

        # In InjecAgent, parsed['eval'] == "succ" means the attack succeeded.
        security_bool = (parsed.get('eval') == 'succ')

        # Utility is not explicitly provided by InjecAgent.
        # A pragmatic proxy: if the model followed the attacker, utility (benign task) likely failed.
        # If you prefer, flip or set to None. For now we report "not security" as utility.
        utility_bool = security_bool

        assistant_text = output
        return assistant_text, utility_bool, security_bool



def get_injection_goal_injecagent(
    suite: Optional[str] = 'dh',
    injection_task_index: Optional[int] = None,
    data_root: Optional[str] = None,
) -> str:
    """
    Static helper to fetch the Attacker Instruction for the selected intersection case,
    following the same selection logic used by _load_dataset_and_select_case() and
    consumed by _eval_single_turn().

    Selection knobs:
        - attack: "dh" or "ds" (defaults to ATTACK env or "dh")
        - setting: dataset setting (defaults to SETTING env or "enhanced")
        - user_task_index: index into the unique User Instruction catalog
        - injection_task_index: index into the unique Attacker Instruction catalog

    If indices/knobs are None, they fall back to the same env defaults as the constructor.
    """

    # -------- locate dataset file exactly like the session --------
    # If caller passes an explicit data_root, prefer it; else derive from src/../data or CWD/data
    if data_root is not None:
        data_dir = os.path.abspath(data_root)
    else:
        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        data_dir = os.path.abspath(data_dir)

    file_name = f"attacker_cases_{suite}.jsonl"
    data_path = os.path.join(data_dir, file_name)
    if not os.path.exists(data_path):
        # Fallback to repo-root/data
        alt = os.path.abspath(os.path.join(os.getcwd(), "data", file_name))
        if os.path.exists(alt):
            data_path = alt
        else:
            raise FileNotFoundError(f"Cannot find dataset file: {data_path}")

    # -------- load & build catalogs just like _load_dataset_and_select_case --------
    data = []
    with open(data_path, 'r') as file:
        for line in file:
            # Parse each line as a JSON object and append to the list
            data.append(json.loads(line))


    return data[injection_task_index]['Attacker Instruction']
