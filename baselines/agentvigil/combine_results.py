"""
Combine ASR results from fuzzing and testing runs into a single report.

Reads the per_test_case_results from each results.json, merges them,
and recomputes ASR + utility rate overall and by suite.

Run from PentestingAgent/ root:
    python Baselines/AgentVigil/combine_results.py \
        --fuzzing  ../../Data/Logs/agentvigil/fuzzing_set/results.json \
        --testing  ../../Data/Logs/agentvigil/testing_set/results.json \
        --output   ../../Data/Logs/agentvigil/combined_results.json
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List


def load_cases(path: str) -> List[Dict]:
    with open(path) as f:
        data = json.load(f)
    cases = data.get("per_test_case_results", [])
    if not cases:
        raise ValueError(f"No per_test_case_results found in {path}")
    return cases


def compute_stats(cases: List[Dict]) -> Dict:
    unique_cases = len(cases)
    cases_attacked = sum(1 for c in cases if c["attacked"])
    cases_with_utility = sum(1 for c in cases if c.get("utility_preserved"))
    return {
        "unique_cases": unique_cases,
        "cases_attacked": cases_attacked,
        "asr": round(cases_attacked / unique_cases, 4) if unique_cases else 0.0,
        "utility_rate": round(cases_with_utility / unique_cases, 4) if unique_cases else 0.0,
    }


def compute_by_suite(cases: List[Dict]) -> Dict:
    suite_stats: Dict[str, Dict] = {}
    for case in cases:
        suite = case["suite"]
        if suite not in suite_stats:
            suite_stats[suite] = {"unique_cases": 0, "cases_attacked": 0, "cases_with_utility": 0}
        suite_stats[suite]["unique_cases"] += 1
        if case["attacked"]:
            suite_stats[suite]["cases_attacked"] += 1
        if case.get("utility_preserved"):
            suite_stats[suite]["cases_with_utility"] += 1

    result = {}
    for suite, counts in sorted(suite_stats.items()):
        uc = counts["unique_cases"]
        ca = counts["cases_attacked"]
        cwu = counts["cases_with_utility"]
        result[suite] = {
            "unique_cases": uc,
            "cases_attacked": ca,
            "asr": round(ca / uc, 4) if uc else 0.0,
            "utility_rate": round(cwu / uc, 4) if uc else 0.0,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description="Combine ASR results from fuzzing and testing runs")
    parser.add_argument("--fuzzing", required=True, help="Path to fuzzing results JSON")
    parser.add_argument("--testing", required=True, help="Path to testing results JSON")
    parser.add_argument("--output", required=True, help="Path to write combined results JSON")
    args = parser.parse_args()

    fuzzing_cases = load_cases(args.fuzzing)
    testing_cases = load_cases(args.testing)

    # Sanity check: detect overlap
    fuzzing_keys = {(c["user_task"], c["injection_task"], c["suite"]) for c in fuzzing_cases}
    testing_keys = {(c["user_task"], c["injection_task"], c["suite"]) for c in testing_cases}
    overlap = fuzzing_keys & testing_keys
    if overlap:
        print(f"WARNING: {len(overlap)} case(s) appear in both sets — deduplicating, keeping fuzzing result.")
        testing_cases = [c for c in testing_cases
                         if (c["user_task"], c["injection_task"], c["suite"]) not in fuzzing_keys]

    all_cases = fuzzing_cases + testing_cases

    combined = {
        "fuzzing_set": compute_stats(fuzzing_cases),
        "testing_set": compute_stats(testing_cases),
        "combined": compute_stats(all_cases),
        "by_suite": compute_by_suite(all_cases),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(combined, f, indent=2)

    print(f"Combined results written to: {output_path}\n")
    print(f"{'Set':<12}  {'Cases':>6}  {'Attacked':>8}  {'ASR':>6}  {'Utility':>7}")
    print("-" * 48)
    for label, key in [("Fuzzing", "fuzzing_set"), ("Testing", "testing_set"), ("Combined", "combined")]:
        s = combined[key]
        print(f"{label:<12}  {s['unique_cases']:>6}  {s['cases_attacked']:>8}  {s['asr']:>6.4f}  {s['utility_rate']:>7.4f}")
    print()
    print(f"{'Suite':<12}  {'Cases':>6}  {'Attacked':>8}  {'ASR':>6}  {'Utility':>7}")
    print("-" * 48)
    for suite, s in combined["by_suite"].items():
        print(f"{suite:<12}  {s['unique_cases']:>6}  {s['cases_attacked']:>8}  {s['asr']:>6.4f}  {s['utility_rate']:>7.4f}")


if __name__ == "__main__":
    main()
