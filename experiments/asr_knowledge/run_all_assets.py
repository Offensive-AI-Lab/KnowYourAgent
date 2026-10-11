#!/usr/bin/env python3
"""
Run a list of knowledge assets sequentially across all 4 suites.

For each asset, the 4 suites are processed one after another.
Within each suite run, triplets are parallelised via --workers.

Usage:
    python run_all_assets.py --workers 8
    python run_all_assets.py --workers 4 --create-only
    python run_all_assets.py --workers 8 --test-only
"""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "benchmarks" / "agentdojo" / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

from run_experiment import (
    DEFAULT_OUTPUT_ROOT,
    RunLogger,
    _derive_output_dir,
    generate_payloads,
    test_payloads,
)

# ── What to run ──────────────────────────────────────────────────────────────

SUITES = ["banking", "slack", "workspace", "travel"]

ASSETS = [
    "benign_response",
    "behavioral_rules",
    "type_of_agent",
    "user_persona",
    "agent_task",
    "model_identity",
    "injected_tool_output",
    "defenses",
    "exception_schema",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_suite_config(suite: str) -> dict:
    path = SCRIPT_DIR / "configs" / "suites" / f"{suite}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _single_asset_config(base: dict, asset_id: str) -> dict:
    cfg = deepcopy(base)
    cfg["knowledge_pieces"] = {k: (k == asset_id) for k in cfg["knowledge_pieces"]}
    return cfg


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run each knowledge asset sequentially across all 4 suites.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_all_assets.py --workers 8              # full pipeline
  python run_all_assets.py --workers 8 --create-only  # generate payloads only
  python run_all_assets.py --workers 8 --test-only    # test existing payloads
""",
    )
    parser.add_argument("--workers",      type=int, default=1,
                        help="Parallel workers for triplets within each suite run (default: 1).")
    parser.add_argument("--defense",      default=None,
                        help="AgentDojo defense to apply (e.g. repeat_user_prompt, "
                             "spotlighting_with_delimiting, tool_filter). Default: none.")
    parser.add_argument("--no-knowledge", action="store_true",
                        help="Run only the no-knowledge baseline (all assets disabled) "
                             "instead of the per-asset list.")
    parser.add_argument("--output-root",  default=str(DEFAULT_OUTPUT_ROOT),
                        help=f"Root for output paths (default: {DEFAULT_OUTPUT_ROOT}).")
    parser.add_argument("--create-only",  action="store_true",
                        help="Generate payloads only; skip testing.")
    parser.add_argument("--test-only",    action="store_true",
                        help="Test existing payloads only; skip generation.")
    args = parser.parse_args()

    output_root = Path(args.output_root)
    assets_to_run = [None] if args.no_knowledge else ASSETS
    total = len(assets_to_run) * len(SUITES)
    run_idx = 0

    for asset_id in assets_to_run:
        label = asset_id if asset_id else "no_knowledge"
        print(f"\n{'=' * 72}")
        print(f"  ASSET: {label}")
        print(f"{'=' * 72}")

        for suite in SUITES:
            run_idx += 1
            base_cfg = _load_suite_config(suite)
            if asset_id is None:
                config = deepcopy(base_cfg)
                config["knowledge_pieces"] = {k: False for k in config["knowledge_pieces"]}
            else:
                config = _single_asset_config(base_cfg, asset_id)
            config["defense"] = args.defense

            output_dir    = _derive_output_dir(config, output_root)
            payloads_path = output_dir / "payloads.json"
            results_path  = output_dir / "results.json"
            log_path      = output_dir / "run.log"

            print(f"\n[{run_idx}/{total}] {suite} / {label}")
            print(f"  → {output_dir}")

            # Skip if already complete
            if not args.create_only and results_path.exists():
                print(f"  [skip] results.json already exists — delete it to rerun.")
                continue
            if args.create_only and payloads_path.exists():
                print(f"  [skip] payloads.json already exists — delete it to regenerate.")
                continue

            logger = RunLogger(log_path)
            logger.header(config, SCRIPT_DIR / "configs" / "suites" / f"{suite}.json")
            if args.workers > 1:
                logger.print(f"Workers : {args.workers} (parallel)")

            try:
                if not args.test_only:
                    generate_payloads(config, payloads_path, workers=args.workers)

                if not args.create_only:
                    if not payloads_path.exists():
                        print(f"  [skip] payloads.json not found — run without --test-only first.")
                        continue
                    test_payloads(payloads_path, results_path, config,
                                  logger=logger, workers=args.workers)
            finally:
                logger.close()

    print(f"\n{'=' * 72}")
    print(f"  All done — {run_idx} runs completed.")
    print(f"  Results under: {output_root}")
    print(f"{'=' * 72}\n")


if __name__ == "__main__":
    main()
