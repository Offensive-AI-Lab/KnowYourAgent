#!/usr/bin/env python3
"""
Re-run failed attacks from an existing results.json.

For every entry in the input results where security=False, generates a new
payload and tests it, repeating up to --iterations times or until
security=True (whichever comes first).  Entries that already have
security=True are kept as-is.

Usage:
    python rerun.py --input results/run1/results.json --iterations 3 --output results/run1_rerun/results.json
"""

import argparse
import json
import sys
from pathlib import Path

# --------------- PATH SETUP ---------------
SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "benchmarks" / "agentdojo" / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

# --------------- IMPORTS ---------------
from run_singular_banking import (
    generate_single_payload,
    test_single_payload,
    serialize_messages,
    VERBOSE,
)


def rerun_failed(
    input_path: Path,
    output_path: Path,
    iterations: int,
    config_path: Path | None = None,
) -> dict:
    """Re-run entries with security=False.

    Args:
        input_path:  Path to the original results.json.
        output_path: Path where the updated results.json will be written.
        iterations:  Max re-attempts per failed entry.
        config_path: Optional path to an attack config JSON.  When provided,
                     its ``knowledge_pieces`` are used for payload generation.
                     When omitted, the config is inferred from the results
                     directory structure.
    """
    with open(input_path, "r") as f:
        original_results = json.load(f)

    # --- Resolve attack config ---
    config = _resolve_config(input_path, config_path)

    results = {}
    rerun_count = 0
    flipped_count = 0

    for key, entry in original_results.items():
        # Keep already-successful entries unchanged
        if entry.get("security") is True:
            results[key] = entry
            continue

        # Skip entries with errors and no payload
        if "error" in entry and "payload" not in entry:
            results[key] = entry
            continue

        parts = key.split("/")
        if len(parts) != 3:
            print(f"  [SKIP] Malformed key: {key}")
            results[key] = entry
            continue

        suite_name, injection_task_id, user_task_id = parts
        rerun_count += 1

        for attempt in range(1, iterations + 1):
            print(f"  [{key}] Re-run attempt {attempt}/{iterations}")

            # --- Generate new payload ---
            try:
                payload = generate_single_payload(
                    config, suite_name, injection_task_id, user_task_id,
                )
            except KeyError as e:
                print(f"    [SKIP] Task not found: {e}")
                results[key] = entry  # keep original
                break

            if VERBOSE:
                print(f"    Payload (first 120 chars): {payload[:120]}...")

            # --- Test ---
            try:
                result_entry = test_single_payload(
                    suite_name, injection_task_id, user_task_id, payload,
                )
                results[key] = result_entry
                print(
                    f"    Security: {result_entry['security']}  |  "
                    f"Utility: {result_entry['utility']}"
                )

                if result_entry.get("security") is True:
                    print(f"    -> Flipped to success on attempt {attempt}.")
                    flipped_count += 1
                    break
            except Exception as exc:
                print(f"    Error: {exc}")
                results[key] = {"payload": payload, "error": str(exc)}
                break
        else:
            # All iterations exhausted without success – keep last attempt
            if key not in results:
                results[key] = entry

    # --- Write output ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    # --- Summary ---
    total = len(results)
    success = sum(1 for r in results.values() if r.get("security") is True)
    errors = sum(1 for r in results.values() if "error" in r)
    print(f"\n  Re-ran {rerun_count} failed entries (max {iterations} attempts each).")
    print(f"  Flipped to success: {flipped_count}")
    print(f"  Saved {total} results → {output_path}")
    if total - errors > 0:
        print(
            f"  ASR: {success}/{total - errors}"
            f" ({success / (total - errors) * 100:.1f}%)"
        )
    return results


def _resolve_config(input_path: Path, config_path: Path | None) -> dict:
    """Load or infer the attack config for payload generation."""
    if config_path is not None:
        with open(config_path, "r") as f:
            return json.load(f)

    # Try to find a config.json next to the results file
    candidate = input_path.parent / "config.json"
    if candidate.is_file():
        with open(candidate, "r") as f:
            return json.load(f)

    # Infer knowledge pieces from the directory name
    # Convention: directory names like "operational_rules_benign_response"
    # contain the enabled knowledge pieces separated by underscores.
    from general_attacker import KNOWLEDGE_PIECE_NAMES

    dir_name = input_path.parent.name
    knowledge_pieces = {name: False for name in KNOWLEDGE_PIECE_NAMES}

    # Try matching each knowledge piece name in the directory name
    for name in KNOWLEDGE_PIECE_NAMES:
        if name in dir_name:
            knowledge_pieces[name] = True

    enabled = [k for k, v in knowledge_pieces.items() if v]
    if not enabled:
        print(
            f"  [WARN] Could not infer knowledge pieces from directory '{dir_name}'. "
            f"All pieces disabled. Use --config to specify explicitly."
        )

    print(f"  Inferred knowledge pieces: {enabled}")
    return {"knowledge_pieces": knowledge_pieces, "triplets": []}


def main():
    parser = argparse.ArgumentParser(
        description="Re-run failed (security=False) attacks from an existing results.json."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the original results.json file.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        required=True,
        help="Max number of re-attempts per failed entry.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path for the output results.json file.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to attack config JSON (overrides auto-inference of knowledge pieces).",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.is_file():
        print(f"[ERROR] Input file not found: {input_path}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Input:      {input_path}")
    print(f"Output:     {output_path}")
    print(f"Iterations: {args.iterations}")
    print(f"{'='*60}\n")

    config_path = Path(args.config) if args.config else None
    rerun_failed(input_path, output_path, args.iterations, config_path)

    print(f"\n{'='*60}")
    print("All done.")


if __name__ == "__main__":
    main()
