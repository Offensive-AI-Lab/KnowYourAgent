#!/usr/bin/env python3
"""
AutoHijacker — Resume an interrupted run.

Loads an existing partial results JSON, skips already-completed cases,
and continues from where the run left off, writing back to the same file.

Usage (from PentestingAgent/):
    python Baselines/AutoHijacker/autohijacker_resume.py \
        --results runs/autohijacker/results_20260512_084716.json \
        [--config  Baselines/AutoHijacker/autohijacker_agentdojo_config.json]
"""

import os
import sys
import json
import argparse
import datetime
from pathlib import Path

os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "Benchmarks" / "agentdojo_edited" / "src"))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from autohijacker_agentdojo_runner import (
    load_config,
    build_case_list,
    run_one_case,
    aggregate,
    save_results,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume an interrupted AutoHijacker run")
    parser.add_argument("--results", "-r", type=Path, required=True,
                        help="Path to the partial results JSON to resume")
    parser.add_argument("--config", "-c", type=Path,
                        default=_HERE / "autohijacker_agentdojo_config.json",
                        help="Path to autohijacker_agentdojo_config.json")
    args = parser.parse_args()

    if not args.results.exists():
        print(f"[ERROR] Results file not found: {args.results}")
        sys.exit(1)

    # Load existing partial results
    with open(args.results, "r", encoding="utf-8") as fh:
        existing = json.load(fh)

    results = existing["results"]
    metadata = existing["metadata"]
    completed = {(r["suite"], r["user_task"], r["injection_task"]) for r in results}
    print(f"Loaded {len(results)} completed cases from {args.results}")

    # Build full case list from config
    cfg = load_config(args.config)
    test_cfg = cfg["test"]
    train_cfg = cfg["training"]
    target_model: str = test_cfg.get("target_model", train_cfg.get("target_model", "gpt-4.1-2025-04-14"))
    llm_model: str = test_cfg.get("llm_model", train_cfg.get("llm_model", "gpt-4.1-2025-04-14"))

    all_cases = build_case_list(test_cfg, smoke_test=False)
    remaining = [(s, ut, it) for s, ut, it in all_cases if (s, ut, it) not in completed]
    print(f"Remaining cases: {len(remaining)} / {len(all_cases)}")

    if not remaining:
        print("All cases already complete — nothing to do.")
        return

    next_s, next_ut, next_it = remaining[0]
    print(f"Resuming from: {next_s} / {next_ut} / {next_it}")
    print("=" * 60)

    output_path = args.results

    for i, (suite, ut, it) in enumerate(remaining, start=len(results) + 1):
        print(f"\n[{i}/{len(all_cases)}] {suite} / {ut} / {it}")

        r = run_one_case(
            suite=suite,
            user_task=ut,
            injection_task=it,
            target_model=target_model,
            llm_model=llm_model,
            output_dir=output_path.parent,
        )
        results.append(r)

        status = "SUCCESS" if r["attack_success"] else "FAIL"
        util_str = "utility=T" if r["utility"] else "utility=F"
        err_str = "  [ERROR]" if r["error"] else ""
        print(f"  → attack={status}, {util_str}{err_str}")

        save_results(results, output_path, metadata)

    summary = aggregate(results)
    print("\n" + "=" * 60)
    print("  FINAL RESULTS SUMMARY")
    print("=" * 60)
    print(f"  Overall ASR     : {summary['overall_asr']:.1%}  ({summary['total_successes']}/{summary['total_cases']})")
    print(f"  Overall Utility : {summary['overall_utility_rate']:.1%}  ({summary['total_utility']}/{summary['total_cases']})")
    if summary["total_errors"]:
        print(f"  Errors          : {summary['total_errors']}")
    for suite_name, s in summary["by_suite"].items():
        print(f"  {suite_name:10s}  ASR={s['asr']:.1%} ({s['successes']}/{s['total']})  utility={s['utility_rate']:.1%}")
    print("=" * 60)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
