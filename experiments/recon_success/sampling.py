"""
sampling.py — Builds a ready-to-run config for main.py by randomly sampling AgentDojo
(suite, user_task) cases and auto-picking one injectable injection_task per case.

A "case" here is a (suite, user_task) pair -- there are only 97 unique pairs across all
4 AgentDojo suites, so requesting more than that yields all 97 (with a warning), never
duplicates.

Usage:
    uv run python ReconSuccessExperiment/sampling.py --num-cases 100 --seed 42
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "benchmarks", "agentdojo", "src"))

from dotenv import load_dotenv

load_dotenv()

from agentdojo.task_suite.load_suites import get_suite
from benchmarks.agentdojo.src.api import AgentDojoChatSession

SUITES = ["banking", "slack", "travel", "workspace"]

DEFAULT_REQUIREMENTS = [
    "tool_names_and_parameters",
    "guardrails",
    "structural_defenses",
    "behavioral_rules",
    "model_identity",
    "type_of_agent",
]


def _is_injectable(suite_name: str, user_task_id: str, injection_task_id: str, target_model: str) -> bool:
    try:
        session = AgentDojoChatSession(
            suite_name=suite_name,
            user_task_id=user_task_id,
            model_name=target_model,
            injection_task_name=injection_task_id,
        )
        session._get_injection_candidates()
        return True
    except Exception:
        return False


def find_injectable_injection_task(suite_name, user_task_id, injection_task_ids, target_model, rng):
    candidates = list(injection_task_ids)
    rng.shuffle(candidates)
    for inj_id in candidates:
        if _is_injectable(suite_name, user_task_id, inj_id, target_model):
            return inj_id
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Sample AgentDojo (suite, user_task) cases for ReconSuccessExperiment."
    )
    parser.add_argument("--num-cases", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target-model", default="gpt-4.1-2025-04-14")
    parser.add_argument("--recon-model", default="gpt-5")
    parser.add_argument("--judge-model", default="gpt-4.1-2025-04-14")
    parser.add_argument(
        "--output",
        default=None,
        help="Where to write the config JSON (default: ReconSuccessExperiment/configs/sampled_<n>.json)",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)

    pairs = []
    suite_cache = {}
    for suite_name in SUITES:
        suite = get_suite("v1", suite_name)
        suite_cache[suite_name] = suite
        for user_task_id in suite.user_tasks:
            pairs.append((suite_name, user_task_id))

    if args.num_cases > len(pairs):
        print(
            f"Warning: requested {args.num_cases} cases but only {len(pairs)} unique "
            f"(suite, user_task) pairs exist across all suites. Using all {len(pairs)}."
        )

    sampled_pairs = rng.sample(pairs, min(args.num_cases, len(pairs)))

    cases = []
    skipped = []
    for suite_name, user_task_id in sampled_pairs:
        suite = suite_cache[suite_name]
        injection_task_ids = list(suite.injection_tasks.keys())
        chosen = find_injectable_injection_task(suite_name, user_task_id, injection_task_ids, args.target_model, rng)
        if chosen is None:
            skipped.append((suite_name, user_task_id))
            continue
        cases.append({"suite": suite_name, "user_task": user_task_id, "injection_task": chosen})

    config = {
        "recon_model": args.recon_model,
        "target_model": args.target_model,
        "judge_model": args.judge_model,
        "system_message_name": None,
        "requirements": DEFAULT_REQUIREMENTS,
        "requirement_defenses": {"structural_defenses": "spotlighting_with_delimiting"},
        "output_dir": f"ReconSuccessExperiment/results/run_{len(cases)}cases_seed{args.seed}",
        "cases": cases,
    }

    output_path = Path(args.output) if args.output else Path(_THIS_DIR) / "configs" / f"sampled_{len(cases)}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"Wrote {len(cases)} cases to {output_path} ({len(skipped)} pairs skipped as non-injectable).")
    if skipped:
        print("Skipped pairs:", skipped)


if __name__ == "__main__":
    main()
