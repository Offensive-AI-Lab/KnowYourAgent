"""
AgentVigil Integration with InjecAgent benchmark.
Provides InjecAgentTemplateTarget for MCTS-based template evaluation against
the InjecAgent benchmark's "dh" (direct harm) and "ds" (data stealing) suites.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from baselines.agentvigil.agentvigil import TargetInterface
from benchmarks.injecagent.src.api import InjecAgentChatSession

logger = logging.getLogger(__name__)


def load_injecagent_test_cases(
    suite: str,
    data_dir: str,
) -> Tuple[List[str], List[str], List[Tuple[int, int]]]:
    """
    Load InjecAgent test cases for a given suite ("dh" or "ds").

    Replicates the catalog-building logic from InjecAgentChatSession so that
    (user_idx, inject_idx) tuples produced here map 1-to-1 to what the session
    expects.

    Returns:
        user_catalog   – ordered list of unique User Instruction strings
        inject_catalog – ordered list of unique Attacker Instruction strings
        valid_pairs    – unique (user_idx, inject_idx) pairs that have at least
                         one matching test case in the JSON
    """
    setting = os.environ.get("SETTING", "enhanced")
    path = Path(data_dir) / f"test_cases_{suite}_{setting}.json"
    with open(path, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    # Build catalogs (deterministic insertion order, matching InjecAgentChatSession)
    user_catalog: List[str] = []
    inject_catalog: List[str] = []
    u_to_idx: Dict[str, int] = {}
    i_to_idx: Dict[str, int] = {}

    for item in test_cases:
        u = item.get("User Instruction", "").strip()
        a = item.get("Attacker Instruction", "").strip()
        if u not in u_to_idx:
            u_to_idx[u] = len(user_catalog)
            user_catalog.append(u)
        if a not in i_to_idx:
            i_to_idx[a] = len(inject_catalog)
            inject_catalog.append(a)

    # Enumerate unique (user_idx, inject_idx) pairs that have a valid test case
    valid_pairs: List[Tuple[int, int]] = []
    seen_pairs: set = set()
    for item in test_cases:
        u = item.get("User Instruction", "").strip()
        a = item.get("Attacker Instruction", "").strip()
        pair = (u_to_idx[u], i_to_idx[a])
        if pair not in seen_pairs:
            valid_pairs.append(pair)
            seen_pairs.add(pair)

    return user_catalog, inject_catalog, valid_pairs


class InjecAgentTemplateTarget(TargetInterface):
    """
    Target interface for template-based attacks against InjecAgent.
    Supports both "dh" (direct harm) and "ds" (data stealing) attack types.
    """

    def __init__(self, target_model: str, data_dir: str):
        self.target_model = target_model
        self.data_dir = data_dir
        self.query_count = 0
        # Pre-load catalogs for both suites so the main loop never hits disk
        self._catalogs: Dict[str, Tuple[List[str], List[str]]] = {}
        for suite in ["dh", "ds"]:
            user_cat, inject_cat, _ = load_injecagent_test_cases(suite, data_dir)
            self._catalogs[suite] = (user_cat, inject_cat)
            logger.info(
                f"Loaded InjecAgent suite '{suite}': "
                f"{len(user_cat)} user tasks, {len(inject_cat)} injection tasks"
            )

    def query(
        self,
        template: str,
        user_task: str,
        injection_task: str,
        suite: str,
        **kwargs,
    ) -> Dict:
        self.query_count += 1
        _, inject_catalog = self._catalogs[suite]
        malicious_goal = inject_catalog[int(injection_task)]
        payload = self._format_template(template, malicious_goal)

        try:
            session = InjecAgentChatSession(
                suite_name=suite,
                user_task_id=user_task,
                model_name=self.target_model,
                injection_task_name=injection_task,
            )

            # Manually initialize history to avoid the extra model call that
            # init_chat() makes with the unmodified (placeholder) template.
            item = session._selected_item
            session.history = [
                {
                    "role": "user",
                    "content": [{"type": "text", "content": item["User Instruction"]}],
                },
                {
                    "role": "assistant",
                    "content": [{"type": "text", "content": item["Thought"]}],
                },
                {
                    "role": "tool",
                    "content": [{"type": "text", "content": item["Tool Response Template"]}],
                    "tool_name": item.get("User Tool", "synthetic_tool"),
                },
            ]
            session._initialized = True

            messages, success_str, utility_str = session.inject_at_tool_message(payload)

        except Exception as e:
            logger.error(
                f"Error in InjecAgent query "
                f"(suite={suite} user={user_task} inject={injection_task}): {e}"
            )
            return {
                "malicious_goal": malicious_goal,
                "payload": payload,
                "response": f"ERROR: {e}",
                "conversation": [],
                "success": False,
                "utility": False,
            }

        conversation = messages if isinstance(messages, list) else []
        return {
            "malicious_goal": malicious_goal,
            "payload": payload,
            "response": str(messages),
            "conversation": conversation,
            "success": "True" in str(success_str),
            "utility": "True" in str(utility_str),
        }

    def reset(self) -> None:
        pass

    def get_query_count(self) -> int:
        return self.query_count

    @staticmethod
    def _format_template(
        template: str,
        malicious_goal: str,
        user_task: str = "",
        model_name: str = "",
    ) -> str:
        if "{malicious_goal}" not in template:
            template = f"{template} {{malicious_goal}}"
        return template.format(
            malicious_goal=malicious_goal,
            user_task=user_task,
            model_name=model_name,
        )
