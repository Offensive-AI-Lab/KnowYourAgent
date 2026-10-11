"""
Update the testing config to use the top N templates from fuzzing results.

Reads top_templates from the fuzzing results JSON, writes them into the
testing config, and sets iterations=0 so AgentDojo.py runs direct evaluation
(no MCTS mutations — the exact best templates are tested as-is).

Run from PentestingAgent/ root:
    python Baselines/AgentVigil/update_testing_config.py \
        --fuzzing-results ../../Data/Logs/agentvigil/fuzzing_set/results.json \
        --testing-config  Baselines/AgentVigil/agentvigil_testing_set.json \
        --top-n 5
"""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fuzzing-results", required=True, help="Path to fuzzing results JSON")
    parser.add_argument("--testing-config",  required=True, help="Path to testing config JSON (modified in place)")
    parser.add_argument("--top-n", type=int, default=5, help="Number of best templates to use (default: 5)")
    args = parser.parse_args()

    with open(args.fuzzing_results) as f:
        fuzzing_results = json.load(f)

    top_templates = [t["template"] for t in fuzzing_results.get("top_templates", [])][:args.top_n]
    if not top_templates:
        print("ERROR: No top_templates found in fuzzing results.", file=sys.stderr)
        sys.exit(1)

    with open(args.testing_config) as f:
        testing_config = json.load(f)

    for run in testing_config:
        run["agent_vigil_config"]["templates"] = top_templates
        run["agent_vigil_config"]["iterations"] = 0  # direct eval, no MCTS

    with open(args.testing_config, "w") as f:
        json.dump(testing_config, f, indent=2)

    print(f"Updated {args.testing_config}: {len(top_templates)} best templates, iterations=0 (direct eval)")
    for i, t in enumerate(top_templates, 1):
        print(f"  {i}. {t[:90]}")


if __name__ == "__main__":
    main()
