"""
AutoHijacker — Stage 2: Test Stage (One-Step Generation)

Given new external data (D) and an attack goal (G):
    1. The Prompter generates a meta-prompt using the trained attack memory
       stored in ``attack_memory.json``.
    2. The Attacker generates the final injection data (D_hat).

No scoring or victim-model querying happens in this stage.
"""

import os
import sys

# Disable CrewAI telemetry (avoids noisy connection-refused errors)
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"

# Ensure AutoHijacker directory is on sys.path for bare imports
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import json
from pathlib import Path
from typing import Any, Dict, List

from crewai import Crew, Process

# ---------------------------------------------------------------------------
# Agent / task factories
# ---------------------------------------------------------------------------
from prompter.agents import create_prompter_agent
from prompter.tasks import create_meta_prompt_task

from attacker.agents import create_attacker_agent
from attacker.tasks import create_injection_task

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MEMORY_FILE = Path(__file__).resolve().parent / "attack_memory.json"


# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------

def _json_dict_to_entry(d: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a JSON-schema dict back to the internal memory format."""
    return {
        "D": d["external_data_D"],
        "G": d["attack_goal_G"],
        "M": d["meta_prompt_M"],
        "D_hat": d["injection_data_D_hat"],
        "S": d["score_S"],
    }


def load_memory_file() -> List[Dict[str, Any]]:
    """Load the trained attack memory from ``attack_memory.json``.

    Returns a flat list of internal-format entries (top + bottom) that
    the Prompter can use as contrastive context.
    """
    if not MEMORY_FILE.exists():
        print(f"[Warning] {MEMORY_FILE} not found — running without memory.")
        return []

    with open(MEMORY_FILE, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    entries: List[Dict[str, Any]] = []
    for d in data.get("top_attacks", []):
        entries.append(_json_dict_to_entry(d))
    for d in data.get("bottom_attacks", []):
        entries.append(_json_dict_to_entry(d))
    return entries


# ---------------------------------------------------------------------------
# Stage 2: Test Stage
# ---------------------------------------------------------------------------

def test_stage(
    original_data: str,
    attack_goal: str,
    llm: str = "gpt-4o",
) -> str:
    """Run a single-step generation using the trained attack memory.

    Args:
        original_data: The new original external data (D).
        attack_goal: The malicious attack goal (G).
        llm: The language model identifier for all agents.

    Returns:
        The final injection data (D_hat) as a string.
    """
    # Load the trained attack memory from the JSON file
    attack_memory = load_memory_file()
    print(f"[Test Stage] Loaded {len(attack_memory)} entries from {MEMORY_FILE}")

    prompter_agent = create_prompter_agent(llm=llm)
    attacker_agent = create_attacker_agent(llm=llm)

    # ---- Step 1: Prompter generates meta-prompt ----
    prompter_task = create_meta_prompt_task(
        agent=prompter_agent,
        original_data=original_data,
        attack_goal=attack_goal,
        attack_memory=attack_memory,
    )

    prompter_crew = Crew(
        agents=[prompter_agent],
        tasks=[prompter_task],
        process=Process.sequential,
        verbose=True,
    )
    prompter_result = prompter_crew.kickoff()
    meta_prompt: str = str(prompter_result)

    # ---- Step 2: Attacker generates final injection data ----
    attacker_task = create_injection_task(
        agent=attacker_agent,
        meta_prompt=meta_prompt,
        original_data=original_data,
        attack_goal=attack_goal,
    )

    attacker_crew = Crew(
        agents=[attacker_agent],
        tasks=[attacker_task],
        process=Process.sequential,
        verbose=True,
    )
    attacker_result = attacker_crew.kickoff()
    injection_data: str = str(attacker_result)

    print(f"\n[Test Stage] Generated injection data (D_hat):\n{injection_data}")
    return injection_data


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    LLM_MODEL = "gpt-4o"

    print("=" * 60)
    print("  STAGE 2: TEST")
    print("=" * 60)
    final_d_hat = test_stage(
        original_data="New unseen external data",
        attack_goal="New attack goal",
        llm=LLM_MODEL,
    )
