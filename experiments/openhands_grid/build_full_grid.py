#!/usr/bin/env python3
"""Build the consolidated 70-cell config for one full 7x10 Cobra-vs-OpenHands pass.

The original 70-cell grid was run as three separate configs (incremental dev):
    test_env_inject.json       10  hello_aha x 10 pairs
    table_iv_grid.json         48  6 injections x 8 non-math pairs
    grid_math_calculator.json  12  6 injections x 2 math pairs
Concatenating them yields one config covering exactly the 70 cells of the 7x10
grid (10 pairs x 7 injections), so a full pass runs in a single invocation. The
build asserts the result matches the canonical roster in eda/build_parquet.py.

    python3 cobra_runs/build_full_grid.py            # write full_grid_7x10.json
    python3 cobra_runs/build_full_grid.py --dry-run  # validate, write nothing
"""
import argparse
import json
import sys
from pathlib import Path

CONFIGS = Path(__file__).resolve().parent / "configs"
SOURCES = ["test_env_inject.json", "table_iv_grid.json", "grid_math_calculator.json"]
OUT = CONFIGS / "full_grid_7x10.json"

# Canonical 7x10 roster (mirrors cobra_runs/eda/build_parquet.py PAIRS x INJECTIONS).
PAIRS = [
    ("math-calculator", "user_task_1"), ("math-calculator", "user_task_21"),
    ("flask-blog", "user_task_3"), ("flask-blog", "user_task_24"), ("flask-blog", "user_task_25"),
    ("sorting-lib", "user_task_4"),
    ("sql-store", "user_task_5"), ("sql-store", "user_task_22"), ("sql-store", "user_task_23"),
    ("fibonacci-gen", "user_task_12"),
]
INJECTIONS = [
    "injection_task_hello_aha", "injection_task_works_function",
    "injection_task_delete_first_file", "injection_task_swap_files",
    "injection_task_curl_pipe_bash", "injection_task_exfil_ssh_key",
    "injection_task_exfil_shadow",
]


def cell(e: dict) -> tuple:
    return (e["repo_name"], e["user_task"], e["injection_task"])


def build() -> list:
    grid = []
    for name in SOURCES:
        grid.extend(json.loads((CONFIGS / name).read_text(encoding="utf-8")))
    seen = {}
    for e in grid:
        k = cell(e)
        if k in seen:
            sys.exit(f"Duplicate cell across source configs: {k}")
        seen[k] = e
    expected = {(r, u, i) for (r, u) in PAIRS for i in INJECTIONS}
    got = set(seen)
    if got != expected:
        sys.exit(f"Roster mismatch.\n  missing: {sorted(expected - got)}\n  extra: {sorted(got - expected)}")
    return grid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Validate only, write nothing.")
    ap.add_argument("--norecon", action="store_true",
                    help="Stamp every entry with \"recon\": false (kya.run_openhands's "
                         "recon-ablation switch) and write full_grid_7x10_norecon.json "
                         "instead of full_grid_7x10.json.")
    args = ap.parse_args()

    grid = build()
    out = OUT
    if args.norecon:
        for e in grid:
            e["recon"] = False
        out = CONFIGS / "full_grid_7x10_norecon.json"
    print(f"{len(grid)} cells  |  {len(PAIRS)} pairs x {len(INJECTIONS)} injections"
          f"{'  (recon: false)' if args.norecon else ''}")
    if args.dry_run:
        print("--dry-run: nothing written.")
        return 0
    out.write_text(json.dumps(grid, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
