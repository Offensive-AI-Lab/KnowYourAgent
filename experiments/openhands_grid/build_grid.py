#!/usr/bin/env python3
"""Generate the Table IV injection grid for the Cobra-vs-OpenHands runner.

Cross-products the 8 non-math (repo, user_task) pairs with the 6 injection
tasks -> 48 entries, written to cobra_runs/configs/table_iv_grid.json.

math-calculator is excluded by construction (its pairs are simply not in the
list below), and so is injection_task_hello_aha (already run as the 1x10
baseline). Each entry matches the schema kya.run_openhands consumes; the
runner adds `log_file` per run.

Usage:
    python3 cobra_runs/build_grid.py            # write table_iv_grid.json
    python3 cobra_runs/build_grid.py --dry-run  # print the grid, write nothing
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADVERSARIAL_TASKS = REPO / "pipeline" / "adversarial_tasks.json"
CONVERSATION_IDS = REPO / "pipeline" / "conversation_ids.json"
DEFAULT_OUT = Path(__file__).resolve().parent / "configs" / "table_iv_grid.json"

# The 8 non-math Table IV (repo, user_task) pairs.
PAIRS = [
    ("flask-blog", "user_task_3"),
    ("flask-blog", "user_task_24"),
    ("flask-blog", "user_task_25"),
    ("sorting-lib", "user_task_4"),
    ("sql-store", "user_task_5"),
    ("sql-store", "user_task_22"),
    ("sql-store", "user_task_23"),
    ("fibonacci-gen", "user_task_12"),
]

# The 6 injection tasks besides injection_task_hello_aha.
INJECTIONS = [
    "injection_task_works_function",
    "injection_task_delete_first_file",
    "injection_task_swap_files",
    "injection_task_curl_pipe_bash",
    "injection_task_exfil_ssh_key",
    "injection_task_exfil_shadow",
]

COBRA_CONFIG = "FullAgent"


def load_goals() -> dict:
    """alias -> pentesting_goal, from pipeline/adversarial_tasks.json."""
    data = json.loads(ADVERSARIAL_TASKS.read_text(encoding="utf-8"))
    goals = {t["injection_task_alias"]: t["pentesting_goal"] for t in data["tasks"]}
    missing = [a for a in INJECTIONS if a not in goals]
    if missing:
        sys.exit(f"Error: no pentesting_goal in {ADVERSARIAL_TASKS} for: {missing}")
    return goals


def check_conversations() -> None:
    """Every pair must have a bootstrapped conversation id, else the runner
    cannot harvest its events."""
    ids = json.loads(CONVERSATION_IDS.read_text(encoding="utf-8"))
    have = {(e["repo"], e["user_task"]) for e in ids if e.get("conversation_id")}
    missing = [p for p in PAIRS if p not in have]
    if missing:
        sys.exit(f"Error: no conversation_id in {CONVERSATION_IDS} for: {missing}. "
                 "Bootstrap them first (pipeline/bootstrap_conversations.py).")


def build() -> list:
    goals = load_goals()
    check_conversations()
    grid = []
    for repo, user_task in PAIRS:
        for injection in INJECTIONS:
            grid.append({
                "repo_name": repo,
                "user_task": user_task,
                "injection_task": injection,
                "pentesting_goal": goals[injection],
                "cobra_config": COBRA_CONFIG,
            })
    return grid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help=f"Output path. Default: {DEFAULT_OUT}")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the grid summary, write nothing.")
    args = ap.parse_args()

    grid = build()
    repos = sorted({e["repo_name"] for e in grid})
    injections = sorted({e["injection_task"] for e in grid})
    print(f"{len(grid)} entries  |  {len(repos)} repos  |  {len(injections)} injections")
    print(f"  repos:      {', '.join(repos)}")
    print(f"  injections: {', '.join(injections)}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(grid, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
