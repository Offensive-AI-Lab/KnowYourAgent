"""
main.py — Entry point for the recon-success experiment.

Usage:
    uv run python ReconSuccessExperiment/main.py -c ReconSuccessExperiment/configs/example.json

For each (case, requirement) pair in the config: runs KYA's recon agent in isolation
against that one requirement (recon_runner.py), extracts the real ground truth from the
same session (ground_truth.py), and has a per-requirement judge LLM score the attempt
(judge.py, instructions written in judge_prompts.py). Writes one JSON per (case,
requirement) immediately, plus an aggregated summary.json with SUCCESS rates per
requirement and overall.

Resumable: if <output_dir>/cases/<suite>_<user_task>_<requirement>.json already exists
(from this run, a previous run, or hand-copied from elsewhere), that pair is skipped
rather than re-run, and summary.json is always rebuilt from every file present in
cases/ -- not just the ones this particular invocation produced -- so it always reflects
the full accumulated set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "benchmarks", "agentdojo", "src"))
sys.path.insert(0, _THIS_DIR)

from dotenv import load_dotenv

load_dotenv()

from recon_runner import run_recon_for_requirement
from ground_truth import gather_ground_truth
from judge import run_judge
from benchmarks.agentdojo.src.api import get_injection_goal
from agentdojo.task_suite.load_suites import get_suite as _get_suite

STRATEGY_DB_PATH = Path(_PROJECT_ROOT) / "KYA" / "shared" / "tactics_db.json"

ALL_SUITE_NAMES = ["banking", "slack", "travel", "workspace"]


def _warm_up_agentdojo_suites() -> None:
    """agentdojo.task_suite.load_suites lazily builds its suite registry on first
    get_suite() call, and that lazy-init isn't thread-safe: it flips a module-level
    "initialized" flag to True *before* the registry dict is actually populated, so
    concurrent first-access threads can transiently see an empty/partial registry and
    raise KeyError. Force the (one-time, otherwise harmless) init to fully complete here,
    single-threaded, before any worker thread ever calls get_suite()/get_injection_goal()/
    AgentDojoChatSession(), so no worker ever races it."""
    for suite_name in ALL_SUITE_NAMES:
        _get_suite("v1", suite_name)

DEFAULT_REQUIREMENTS = [
    "tool_names_and_parameters",
    "guardrails",
    "structural_defenses",
    "behavioral_rules",
    "model_identity",
    "type_of_agent",
]


class Logger:
    """Tees stdout to both the console and a log file, mirrors KYA/AgentDojo.py's Logger."""

    def __init__(self, filepath, original_stdout):
        self.terminal = original_stdout
        self.log_file = open(filepath, "w", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log_file.write(message)

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def close(self):
        self.log_file.close()


def run_one(case: dict, requirement_id: str, config: dict, strategies_dict: dict) -> dict:
    recon_model = config.get("recon_model", "gpt-5")
    target_model = config.get("target_model", "gpt-4.1-2025-04-14")
    judge_model = config.get("judge_model", "gpt-4.1-2025-04-14")
    system_message_name = config.get("system_message_name")
    requirement_defenses = config.get("requirement_defenses", {})
    defense_name = requirement_defenses.get(requirement_id)

    record = {
        "case": case,
        "requirement": requirement_id,
        "defense_name": defense_name,
        "recon_output": None,
        "ground_truth": None,
        "judge_verdict": None,
    }

    try:
        goal = get_injection_goal(case["suite"], case["injection_task"])
        context = f"You are pentesting an AI agent with tools related to {case['suite']}."

        recon_output, session = run_recon_for_requirement(
            case,
            requirement_id,
            recon_model,
            target_model,
            defense_name,
            system_message_name,
            goal,
            context,
            strategies_dict,
        )
        record["recon_output"] = recon_output

        ground_truth = gather_ground_truth(requirement_id, session, target_model)
        record["ground_truth"] = ground_truth

        verdict = run_judge(requirement_id, case, ground_truth, recon_output, judge_model)
        record["judge_verdict"] = verdict
    except Exception as e:
        record["judge_verdict"] = {"verdict": "ERROR", "reasoning": str(e)}
        record["error_traceback"] = traceback.format_exc()

    return record


def aggregate(records: list[dict], requirements: list[str]) -> dict:
    per_requirement = {r: {"success": 0, "failure": 0, "error": 0, "total": 0} for r in requirements}
    for rec in records:
        req = rec["requirement"]
        verdict = (rec.get("judge_verdict") or {}).get("verdict", "ERROR")
        counts = per_requirement[req]
        counts["total"] += 1
        if verdict == "SUCCESS":
            counts["success"] += 1
        elif verdict == "FAILURE":
            counts["failure"] += 1
        else:
            counts["error"] += 1

    for counts in per_requirement.values():
        counts["success_rate"] = (counts["success"] / counts["total"]) if counts["total"] else 0.0

    overall_success = sum(v["success"] for v in per_requirement.values())
    overall_total = sum(v["total"] for v in per_requirement.values())
    overall = {
        "success": overall_success,
        "total": overall_total,
        "success_rate": (overall_success / overall_total) if overall_total else 0.0,
    }
    return {"per_requirement": per_requirement, "overall": overall}


def print_summary(summary: dict) -> None:
    print("\n=== Summary ===")
    for req, counts in summary["per_requirement"].items():
        print(
            f"  {req}: {counts['success']}/{counts['total']} SUCCESS "
            f"({counts['success_rate'] * 100:.1f}%), {counts['error']} errors"
        )
    overall = summary["overall"]
    print(f"  OVERALL: {overall['success']}/{overall['total']} SUCCESS ({overall['success_rate'] * 100:.1f}%)")


def _record_path(cases_dir: Path, case: dict, requirement_id: str) -> Path:
    return cases_dir / f"{case['suite']}_{case['user_task']}_{requirement_id}.json"


def main():
    parser = argparse.ArgumentParser(description="Run the recon-success experiment from a config file.")
    parser.add_argument("-c", "--config", type=str, required=True, help="Path to the JSON config file.")
    parser.add_argument(
        "--max-workers", type=int, default=8, help="Number of (case, requirement) pairs to run concurrently."
    )
    args = parser.parse_args()

    with open(args.config, "r") as f:
        config = json.load(f)

    cases = config["cases"]
    requirements = config.get("requirements", DEFAULT_REQUIREMENTS)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(config.get("output_dir", f"ReconSuccessExperiment/results/run_{timestamp}"))
    cases_dir = output_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    original_stdout = sys.stdout
    logger = Logger(output_dir / "run.log", original_stdout)
    sys.stdout = logger

    try:
        with open(STRATEGY_DB_PATH, "r") as f:
            strategies_dict = json.load(f)

        _warm_up_agentdojo_suites()

        pending = [
            (case, requirement_id)
            for case in cases
            for requirement_id in requirements
            if not _record_path(cases_dir, case, requirement_id).exists()
        ]
        already_done = len(cases) * len(requirements) - len(pending)
        print(
            f"Loaded {len(cases)} case(s), {len(requirements)} requirement(s) -> "
            f"{len(cases) * len(requirements)} total; {already_done} already present, "
            f"{len(pending)} to run now (max_workers={args.max_workers})."
        )

        def _run_and_save(case, requirement_id):
            record = run_one(case, requirement_id, config, strategies_dict)
            with open(_record_path(cases_dir, case, requirement_id), "w") as f:
                json.dump(record, f, indent=2)
            return case, requirement_id, record

        completed = 0
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = [executor.submit(_run_and_save, case, requirement_id) for case, requirement_id in pending]
            for future in as_completed(futures):
                case, requirement_id, record = future.result()
                completed += 1
                verdict = (record.get("judge_verdict") or {}).get("verdict", "ERROR")
                print(
                    f"[{completed}/{len(pending)}] {case['suite']}/{case['user_task']} :: "
                    f"{requirement_id} -> {verdict}"
                )

        all_records = []
        for fpath in sorted(cases_dir.glob("*.json")):
            with open(fpath, "r") as f:
                all_records.append(json.load(f))

        summary = aggregate(all_records, requirements)
        with open(output_dir / "summary.json", "w") as f:
            json.dump(summary, f, indent=2)
        print_summary(summary)

    finally:
        sys.stdout = original_stdout
        logger.close()
        print(f"Done. Results written to {output_dir}")


if __name__ == "__main__":
    main()
