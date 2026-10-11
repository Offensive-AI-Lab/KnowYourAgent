#!/usr/bin/env python3
"""
Utility script to run TopicAttack payloads against multiple defenses and compare results.

Usage:
    # Run all defenses against a specific payload
    python run_defense_comparison.py \
        --payload_file data/agentdojo_banking0_attack_complete.json \
        --suite_name banking

    # Run specific defenses against multiple payloads
    python run_defense_comparison.py \
        --payload_patterns "data/agentdojo_*_attack_complete.json" \
        --suite_name banking \
        --defenses spotlighting_with_delimiting repeat_user_prompt

    # Dry run (just show what would be executed)
    python run_defense_comparison.py \
        --payload_file data/agentdojo_banking0_attack_complete.json \
        --suite_name banking \
        --dry_run
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# Default defenses to test
DEFAULT_DEFENSES = [
    "spotlighting_with_delimiting",
    "repeat_user_prompt",
]


def run_defense_evaluation(
    payload_file: str,
    defense_name: str,
    suite_name: str,
    model_name: str,
    api_url: str,
    output_dir: str,
    verbose: bool = False,
    dry_run: bool = False,
) -> tuple[int, str]:
    """
    Run a single defense evaluation and return (exit_code, log_file).
    """
    log_file = os.path.join(
        output_dir,
        f"{suite_name}_{Path(payload_file).stem}_{defense_name}.log"
    )

    cmd = [
        sys.executable,
        "run_topicattack_with_defense.py",
        "--payload_file",
        payload_file,
        "--defense_name",
        defense_name,
        "--suite_name",
        suite_name,
        "--model_name",
        model_name,
        "--api_url",
        api_url,
        "--log_file",
        log_file,
    ]

    if verbose:
        cmd.append("--verbose")

    print(f"\n{'='*70}")
    print(f"Defense: {defense_name}")
    print(f"Payload: {payload_file}")
    print(f"Command: {' '.join(cmd)}")
    print(f"Log file: {log_file}")
    print(f"{'='*70}")

    if dry_run:
        print("[DRY RUN] Would execute the above command")
        return 0, log_file

    try:
        result = subprocess.run(cmd, check=False, cwd=os.getcwd())
        return result.returncode, log_file
    except Exception as e:
        print(f"ERROR: Failed to run defense evaluation: {e}")
        return 1, log_file


def parse_log_summary(log_file: str) -> dict:
    """Extract summary statistics from a log file."""
    stats = {
        "asr": None,
        "utility": None,
        "total": None,
        "errors": None,
    }

    if not os.path.exists(log_file):
        return stats

    try:
        with open(log_file, "r") as f:
            content = f.read()

            # Extract ASR
            for line in content.split("\n"):
                if "ASR  (attack)" in line:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == "(attack)" and i > 0:
                            asr_str = parts[i - 1].rstrip("%")
                            try:
                                stats["asr"] = float(asr_str)
                            except ValueError:
                                pass
                elif "Utility (task)" in line:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == "(task)" and i > 0:
                            util_str = parts[i - 1].rstrip("%")
                            try:
                                stats["utility"] = float(util_str)
                            except ValueError:
                                pass
                elif "Total entries" in line:
                    parts = line.split()
                    if parts[-1].isdigit():
                        stats["total"] = int(parts[-1])
                elif "Errors" in line and ":" in line:
                    parts = line.split(":")
                    if len(parts) > 1 and parts[1].strip().isdigit():
                        stats["errors"] = int(parts[1].strip())

    except Exception as e:
        print(f"Warning: Could not parse log file {log_file}: {e}")

    return stats


def print_comparison_table(
    results: list[tuple[str, str, int, str]]
):
    """Print a comparison table of results."""
    print(f"\n{'='*80}")
    print("DEFENSE COMPARISON SUMMARY")
    print(f"{'='*80}")

    if not results:
        print("No results to display")
        return

    # Extract summaries
    summaries: list[tuple[str, dict]] = []
    for defense_name, payload_name, exit_code, log_file in results:
        if exit_code == 0:
            stats = parse_log_summary(log_file)
            summaries.append((f"{defense_name}", stats))

    if not summaries:
        print("No completed evaluations to summarize")
        return

    # Print table
    print(f"{'Defense':<30} {'ASR':<10} {'Utility':<10} {'Total':<10} {'Errors':<10}")
    print(f"{'-'*60}")

    for defense_name, stats in summaries:
        asr = f"{stats['asr']:.1f}%" if stats["asr"] is not None else "N/A"
        util = f"{stats['utility']:.1f}%" if stats["utility"] is not None else "N/A"
        total = str(stats["total"]) if stats["total"] is not None else "N/A"
        errors = str(stats["errors"]) if stats["errors"] is not None else "N/A"
        print(f"{defense_name:<30} {asr:<10} {util:<10} {total:<10} {errors:<10}")

    print(f"{'='*80}")


def run(args):
    # Create output directory
    output_dir = args.output_dir or f"logs/defense_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(output_dir, exist_ok=True)

    print(f"Output directory: {output_dir}")

    # Determine defenses to test
    defenses = args.defenses or DEFAULT_DEFENSES
    print(f"Defenses to test: {', '.join(defenses)}")

    # Determine payload files
    if args.payload_file:
        payload_files = [args.payload_file]
    elif args.payload_patterns:
        import glob
        payload_files = sorted(glob.glob(args.payload_patterns))
        if not payload_files:
            print(f"ERROR: No files match pattern: {args.payload_patterns}")
            sys.exit(1)
    else:
        print("ERROR: Must provide --payload_file or --payload_patterns")
        sys.exit(1)

    print(f"Payload files: {len(payload_files)}")
    for pf in payload_files:
        print(f"  - {pf}")

    # Run evaluations
    results: list[tuple[str, str, int, str]] = []
    total_tasks = len(defenses) * len(payload_files)
    task_idx = 0

    for defense_name in defenses:
        for payload_file in payload_files:
            task_idx += 1
            print(f"\n[{task_idx}/{total_tasks}] Running evaluation...")

            exit_code, log_file = run_defense_evaluation(
                payload_file=payload_file,
                defense_name=defense_name,
                suite_name=args.suite_name,
                model_name=args.model_name,
                api_url=args.api_url,
                output_dir=output_dir,
                verbose=args.verbose,
                dry_run=args.dry_run,
            )

            payload_name = Path(payload_file).stem
            results.append((defense_name, payload_name, exit_code, log_file))

    # Print comparison
    print_comparison_table(results)

    # Summary
    successful = sum(1 for _, _, code, _ in results if code == 0)
    total = len(results)
    print(f"\nSuccessful runs: {successful}/{total}")
    print(f"Logs saved to: {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run and compare TopicAttack payloads across multiple defenses",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Payload selection
    payload_group = parser.add_mutually_exclusive_group(required=True)
    payload_group.add_argument(
        "--payload_file",
        type=str,
        help="Single payload file to evaluate",
    )
    payload_group.add_argument(
        "--payload_patterns",
        type=str,
        help="Glob pattern for multiple payload files",
    )

    # Defense configuration
    parser.add_argument(
        "--defenses",
        type=str,
        nargs="+",
        default=None,
        help=f"Defenses to test (default: {' '.join(DEFAULT_DEFENSES)})",
    )

    # Environment configuration
    parser.add_argument(
        "--suite_name",
        type=str,
        default="banking",
        help="AgentDojo suite name (default: banking)",
    )
    parser.add_argument(
        "--model_name",
        type=str,
        default="gpt-4o-2024-05-13",
        help="Victim model name (default: gpt-4o-2024-05-13)",
    )
    parser.add_argument(
        "--api_url",
        type=str,
        default="http://127.0.0.1:5000",
        help="REST API server URL (default: http://127.0.0.1:5000)",
    )

    # Output options
    parser.add_argument(
        "--output_dir",
        type=str,
        default=None,
        help="Output directory for logs (default: auto-generated)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        default=False,
        help="Show what would be executed without running",
    )

    args = parser.parse_args()
    run(args)
