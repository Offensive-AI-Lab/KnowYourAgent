"""
Convert experiment log folders into a CSV file.

Each suite folder is expected to contain injection task subfolders (ij0, ij1, ...)
with user task files (ut_0.ans, ut_1.ans, ...) inside them.

Usage:
    python logs_to_csv.py <suite_folder1> [suite_folder2 ...] -o output.csv
    
Example:
    python logs_to_csv.py \
        ../Experiments/CobraV3/AgentDojo/workspace \
        ../Experiments/CobraV3/AgentDojo/travel \
        -o results.csv
"""

import argparse
import csv
import re
from pathlib import Path

from analysis.analysiscode.parse_experiments import parse_file


def collect_rows(suite_folders: list[str]) -> list[dict]:
    """Walk each suite folder and parse every .ans file into a row.

    Args:
        suite_folders: List of paths to suite folders. Each folder should
            contain ij* subfolders with ut_*.ans files.

    Returns:
        List of dicts with keys: suite, user_task, injection_task,
        attack_attempts, result.
    """
    rows = []
    for folder in suite_folders:
        folder = Path(folder)
        suite_name = folder.name  # e.g. "workspace", "travel"

        for ij_dir in sorted(folder.iterdir()):
            if not ij_dir.is_dir() or not re.match(r"ij\d+", ij_dir.name):
                continue
            ij_id = ij_dir.name  # e.g. "ij0"

            for ans_file in sorted(ij_dir.glob("ut_*.ans")):
                # Extract user task number from filename
                ut_match = re.match(r"ut_(\d+)\.ans", ans_file.name)
                if not ut_match:
                    continue
                ut_id = f"ut_{ut_match.group(1)}"

                res = parse_file(str(ans_file))

                if res["is_success"]:
                    result = "success"
                elif res["has_error"]:
                    result = "error"
                else:
                    result = "failure"

                prog_success = False
                if res["programmatic_success"]:
                    prog_success = True 

                total_injections = res["attack_attempts"] + res["env_injection_count"]

                rows.append({
                    "suite": suite_name,
                    "user_task": ut_id,
                    "injection_task": ij_id,
                    "attack_attempts": res["attack_attempts"],
                    "total_injections": total_injections,
                    "result": result,
                    "programmatic_success": res["programmatic_success"],
                    "utility": res["utility"],
                })
    return rows


def write_csv(rows: list[dict], output_path: str) -> None:
    """Write rows to a CSV file."""
    fieldnames = ["suite", "user_task", "injection_task", "attack_attempts", "total_injections", "result"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Convert experiment logs to CSV")
    parser.add_argument(
        "suite_folders",
        nargs="+",
        help="Paths to suite folders (each containing ij*/ut_*.ans)",
    )
    parser.add_argument(
        "-o", "--output",
        default="results.csv",
        help="Output CSV path (default: results.csv)",
    )
    args = parser.parse_args()

    rows = collect_rows(args.suite_folders)
    write_csv(rows, args.output)
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
