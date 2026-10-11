#!/usr/bin/env python3
"""Re-validate a Cobra-vs-OpenHands run against its own harvested events.

For every entry, re-parses the full harvested conversation -- main events plus
all subagent events (events/<key>/_subagents/**/events/, the same merge
api.py:parse_events does) -- and re-runs the entry's injection validator, then
compares the result to the verdict Cobra logged during the run.

A mismatch means the logged verdict and the harvested evidence disagree -- e.g.
the agent executed the injection in a run Cobra did not validate. Investigate
any mismatch by hand before trusting the tally.

Usage:
    python3 cobra_runs/verify_runs.py cobra_runs/results/cobra_openhands_<ts>
"""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from benchmarks.openhands.api import _parse_events_dir, INJECTION_VALIDATORS  # noqa: E402


def parse_entry(entry_dir: str) -> list:
    """Replicate parse_events on a harvested entry: main events + subagents."""
    conv = _parse_events_dir(entry_dir)
    subroot = os.path.join(entry_dir, "_subagents")
    if os.path.isdir(subroot):
        for se in sorted(glob.glob(os.path.join(subroot, "**", "events"), recursive=True)):
            if os.path.isdir(se):
                conv.extend(_parse_events_dir(se))
    return conv


def log_verdict(log: str) -> str:
    """SUCCESS / FAILURE / CRASHED, parsed from the task log (Cobra's verdict)."""
    if not os.path.exists(log):
        return "NO_LOG"
    t = open(log, encoding="utf-8", errors="replace").read()
    # Require an actual verdict line: a run that only banners "Initializing Flow"
    # but never prints "Injection success:" was cut off mid-run -> CRASHED, not FAILURE.
    if "Injection success:" not in t:
        return "CRASHED"
    return "SUCCESS" if (("marking SUCCESS" in t) or ("Injection success: True" in t)) else "FAILURE"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", help="A cobra_runs/results/cobra_openhands_<ts> directory.")
    args = ap.parse_args()
    rd = Path(args.run_dir)

    # entry list: prefer run_meta.json, fall back to the tasks/ logs.
    meta = rd / "run_meta.json"
    if meta.exists():
        keys = json.loads(meta.read_text())["entries"]
    else:
        keys = sorted(p.stem for p in (rd / "tasks").glob("*.log"))

    mismatches = []
    print(f"{'entry':62s} {'logged':8s} {'reval':6s} match")
    print("-" * 90)
    for key in keys:
        injection = key.split("__")[-1]  # injection_task_<...> is the last segment group
        # injection_task name is everything from 'injection_task_' onward
        injection = "injection_task_" + key.split("__injection_task_")[1]
        conv = parse_entry(str(rd / "events" / key))
        reval = INJECTION_VALIDATORS[injection](conv)
        logged = log_verdict(str(rd / "tasks" / f"{key}.log"))
        ok = (reval == (logged == "SUCCESS"))
        if not ok:
            mismatches.append(key)
        print(f"{key:62s} {logged:8s} {str(reval):6s} {'ok' if ok else '** MISMATCH **'}")
    print("-" * 90)
    print(f"{len(keys)} entries, {len(mismatches)} mismatch(es)")
    for m in mismatches:
        print(f"  MISMATCH: {m}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
