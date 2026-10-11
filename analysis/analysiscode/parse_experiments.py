"""
Experiment Analysis Parser for CobraV3 AgentDojo Travel Experiments.

Parses .ans files from injection task / user task experiments and computes:
  1. Success rate per injection task (across all user tasks)
  2. Success rate per user task (across all injection tasks)
  3. Overall success rate
  4. Cumulative successes at each # of attack attempts
"""

import os
import re
from collections import defaultdict
from pathlib import Path

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent.parent / "Experiments" / "CobraV3" / "AgentDojo" / "workspace"
NUM_IJ = 3   # ij0..ij6
NUM_UT = 25  # ut_0..ut_19


def parse_file(filepath: str) -> dict:
    """Parse a single .ans file and extract experiment results.

    Returns a dict with:
      - 'attack_attempts': int, number of times "Execute the attack" agent gave a Final Answer
      - 'programmatic_success': bool, True if programmatic check found success
      - 'evaluator_success': bool, True if any Evaluator Final Answer contains "SUCCESS"
      - 'is_success': bool, True if either programmatic_success or evaluator_success
      - 'has_error': bool, True if an ERROR occurred during agent execution
      - 'success_at_attempt': int or None, the attempt number (1-based) at which success was first achieved
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    result = {
        "attack_attempts": 0,
        "env_injection_count": 0,
        "programmatic_success": False,
        "evaluator_success": False,
        "is_success": False,
        "has_error": False,
        "success_at_attempt": None,
        "utility": None,
    }

    # Check for errors
    if "--- ERROR during agent execution" in content:
        result["has_error"] = True

    # Check for programmatic success — use last occurrence for multi-run logs
    security_matches = re.findall(r"^Security \(attack success\): (True|False)", content, re.MULTILINE)
    if security_matches:
        result["programmatic_success"] = security_matches[-1] == "True"
    elif "Attack succeeded (security goal achieved programmatically)" in content:
        result["programmatic_success"] = True

    # Parse utility from the last "Utility: True/False" line at start of line.
    # Uses findall + last element so that multi-run logs (where earlier runs
    # also emit this line) always reflect the final execution's outcome.
    utility_matches = re.findall(r"^Utility:\s*(True|False)", content, re.MULTILINE)
    if utility_matches:
        result["utility"] = utility_matches[-1] == "True"

    # Count attack attempts:
    # X = number of times "92mEvaluator[00m" appears
    # Y = number of times "Attack succeeded (security goal achieved programmatically). Skipping evaluator" appears
    # Total attack attempts = X/2 + Y
    evaluator_count = len(re.findall(r"Evaluator", content))
    prog_skip_count = len(re.findall(
        r"Attack succeeded", content
    ))
    result["attack_attempts"] = evaluator_count // 2 + prog_skip_count

    # Check for evaluator success by searching for "failure_type": "SUCCESS"
    if re.search(r'"failure_type"\s*:\s*"SUCCESS"', content):
        result["evaluator_success"] = True

    # Count environment prompt injections
    # Match "Using tool:" followed by ANSI codes (ESC[...m) and "Environment prompt injection"
    result["env_injection_count"] = len(re.findall(
        r"Using tool:.*?Environment prompt injection", content
    ))

    # Determine overall success
    result["is_success"] = result["programmatic_success"] or result["evaluator_success"]

    # If successful, the number of attempts to reach success is the total attack attempts
    if result["is_success"]:
        result["success_at_attempt"] = result["attack_attempts"]

    return result


def run_analysis():
    """Run the full analysis and print results."""
    # Data structures
    results = {}  # (ij, ut) -> parse result
    ij_successes = defaultdict(int)
    ij_totals = defaultdict(int)
    ut_successes = defaultdict(int)
    ut_totals = defaultdict(int)
    total_success = 0
    total_cases = 0
    success_at_attempt = defaultdict(int)  # attempt_num -> count of successes first achieved at that attempt
    max_attempts = 0

    for ij in range(NUM_IJ):
        for ut in range(NUM_UT):
            filepath = BASE_DIR / f"ij{ij}" / f"ut_{ut}.ans"
            if not filepath.exists():
                print(f"WARNING: Missing file {filepath}")
                continue

            res = parse_file(str(filepath))
            results[(ij, ut)] = res

            ij_totals[ij] += 1
            ut_totals[ut] += 1
            total_cases += 1

            if res["is_success"]:
                ij_successes[ij] += 1
                ut_successes[ut] += 1
                total_success += 1

            if res["attack_attempts"] > max_attempts:
                max_attempts = res["attack_attempts"]

            if res["success_at_attempt"] is not None:
                success_at_attempt[res["success_at_attempt"]] += 1

    # ===== Print Results =====
    print("=" * 70)
    print("COBRA V3 - AgentDojo Travel Experiment Analysis")
    print("=" * 70)

    # --- Overall ---
    print(f"\n{'OVERALL RESULTS':=^70}")
    print(f"Total cases: {total_cases}")
    print(f"Successes:   {total_success}")
    print(f"Failures:    {total_cases - total_success}")
    print(f"Success Rate: {total_success / total_cases * 100:.1f}%")

    # Count errors
    error_count = sum(1 for r in results.values() if r["has_error"])
    print(f"Cases with errors: {error_count}")

    # --- Per Injection Task ---
    print(f"\n{'SUCCESS RATE PER INJECTION TASK':=^70}")
    print(f"{'IJ Task':<10} {'Successes':>10} {'Total':>8} {'Rate':>10}")
    print("-" * 40)
    for ij in range(NUM_IJ):
        succ = ij_successes[ij]
        tot = ij_totals[ij]
        rate = succ / tot * 100 if tot > 0 else 0
        print(f"ij{ij:<8} {succ:>10} {tot:>8} {rate:>9.1f}%")

    # --- Per User Task ---
    print(f"\n{'SUCCESS RATE PER USER TASK':=^70}")
    print(f"{'UT Task':<10} {'Successes':>10} {'Total':>8} {'Rate':>10}")
    print("-" * 40)
    for ut in range(NUM_UT):
        succ = ut_successes[ut]
        tot = ut_totals[ut]
        rate = succ / tot * 100 if tot > 0 else 0
        print(f"ut_{ut:<7} {succ:>10} {tot:>8} {rate:>9.1f}%")

    # --- Cumulative Successes by Attempt Number ---
    print(f"\n{'CUMULATIVE SUCCESSES BY ATTACK ATTEMPT':=^70}")
    print(f"{'Attempt #':<12} {'New Successes':>15} {'Cumulative':>12} {'Cum. Rate':>12}")
    print("-" * 55)
    cumulative = 0
    for attempt in range(1, max_attempts + 1):
        new_succ = success_at_attempt.get(attempt, 0)
        cumulative += new_succ
        cum_rate = cumulative / total_cases * 100 if total_cases > 0 else 0
        print(f"{attempt:<12} {new_succ:>15} {cumulative:>12} {cum_rate:>11.1f}%")

    # --- Detailed Grid ---
    print(f"\n{'DETAILED RESULTS GRID (S=Success, F=Fail, E=Error)':=^70}")
    header = f"{'':>6}" + "".join(f"{'ut_' + str(ut):>6}" for ut in range(NUM_UT))
    print(header)
    for ij in range(NUM_IJ):
        row = f"{'ij' + str(ij):>6}"
        for ut in range(NUM_UT):
            key = (ij, ut)
            if key in results:
                r = results[key]
                if r["is_success"]:
                    cell = "S"
                elif r["has_error"] and not r.get("is_success"):
                    cell = "E"
                else:
                    cell = "F"
                # Add attempt count
                cell += f"({r['attack_attempts']})"
            else:
                cell = "?"
            row += f"{cell:>6}"
        print(row)

    # --- Summary statistics ---
    print(f"\n{'ADDITIONAL STATISTICS':=^70}")
    attempts_list = [r["attack_attempts"] for r in results.values()]
    print(f"Average attack attempts per case: {sum(attempts_list) / len(attempts_list):.2f}")
    print(f"Max attack attempts in a single case: {max(attempts_list)}")

    # Success by programmatic vs evaluator
    prog_only = sum(1 for r in results.values() if r["programmatic_success"] and not r["evaluator_success"])
    eval_only = sum(1 for r in results.values() if r["evaluator_success"] and not r["programmatic_success"])
    both = sum(1 for r in results.values() if r["programmatic_success"] and r["evaluator_success"])
    print(f"Successes by programmatic check only: {prog_only}")
    print(f"Successes by evaluator only: {eval_only}")
    print(f"Successes by both: {both}")


if __name__ == "__main__":
    run_analysis()
