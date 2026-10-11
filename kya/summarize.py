"""Summarise a run's results.jsonl into attack-success-rate (ASR).

    python -m kya.summarize runs/agentdojo_smoke/results.jsonl

Groups by the first component of each run's ``key`` (the benchmark suite / repo)
and prints per-group and overall ASR. Runs that errored are reported separately
so a crashed run is never silently counted as a failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarise KYA results.jsonl into ASR.")
    ap.add_argument("results", nargs="+", help="One or more results.jsonl files.")
    args = ap.parse_args()

    groups: dict[str, list[dict]] = defaultdict(list)
    errors = 0
    for path in args.results:
        try:
            lines = open(path).read().splitlines()
        except FileNotFoundError:
            print(f"Not found: {path}", file=sys.stderr)
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("error"):
                errors += 1
            key = rec.get("key") or ["(all)"]
            groups[str(key[0])].append(rec)

    if not groups:
        print("No results found.")
        return 1

    total_ok = total_n = 0
    width = max(len(g) for g in groups)
    print(f"{'group':<{width}}  {'success':>8}  {'n':>5}  {'ASR':>6}")
    print(f"{'-' * width}  {'-' * 8}  {'-' * 5}  {'-' * 6}")
    for group in sorted(groups):
        recs = groups[group]
        ok = sum(bool(r.get("security")) for r in recs)
        n = len(recs)
        total_ok += ok
        total_n += n
        print(f"{group:<{width}}  {ok:>8}  {n:>5}  {100 * ok / n:>5.1f}%")
    print(f"{'-' * width}  {'-' * 8}  {'-' * 5}  {'-' * 6}")
    print(f"{'TOTAL':<{width}}  {total_ok:>8}  {total_n:>5}  {100 * total_ok / total_n:>5.1f}%")
    if errors:
        print(f"\nNote: {errors} run(s) errored (counted as non-success above; see their logs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
