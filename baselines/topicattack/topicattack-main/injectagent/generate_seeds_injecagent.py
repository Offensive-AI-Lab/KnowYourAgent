#!/usr/bin/env python3
"""
Generate annotated seed files for all InjecAgent suites and settings.

Reads test cases from Benchmarks/injecagent/data/ and writes annotated copies
to topicattack-main/injectagent/data/ for all four variants:
  - dh  (Direct Harm)  x base / enhanced
  - ds  (Data Stealing) x base / enhanced

Each output item gains four metadata fields that the execution runner needs
to recreate the exact InjecAgentChatSession without re-deriving indices:
  "suite"                - "dh" or "ds"
  "setting"              - "base" or "enhanced"
  "user_task_index"      - index into the unique user-instruction catalog
  "injection_task_index" - index into the unique attacker-instruction catalog

The catalog ordering logic mirrors InjecAgentChatSession._load_dataset_and_select_case()
exactly (first-seen order, whitespace-stripped).

Usage (from repo root or this directory):
    python generate_seeds_injecagent.py
"""

import json
import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
BENCHMARKS_DATA = os.path.join(REPO_ROOT, "Benchmarks", "injecagent", "data")
OUT_DIR = os.path.join(os.path.dirname(__file__), "data")


def _build_catalogs(data: list[dict]) -> tuple[list[str], list[str]]:
    """Return (user_catalog, injection_catalog) — unique, first-seen order."""
    user_set: list[str] = []
    inj_set: list[str] = []
    seen_u: set[str] = set()
    seen_i: set[str] = set()
    for item in data:
        u = item.get("User Instruction", "").strip()
        a = item.get("Attacker Instruction", "").strip()
        if u not in seen_u:
            seen_u.add(u)
            user_set.append(u)
        if a not in seen_i:
            seen_i.add(a)
            inj_set.append(a)
    return user_set, inj_set


def _annotate(data: list[dict], suite: str, setting: str) -> list[dict]:
    user_cat, inj_cat = _build_catalogs(data)
    user_idx = {u: i for i, u in enumerate(user_cat)}
    inj_idx = {a: i for i, a in enumerate(inj_cat)}

    annotated = []
    for item in data:
        entry = dict(item)
        entry["suite"] = suite
        entry["setting"] = setting
        u = item.get("User Instruction", "").strip()
        a = item.get("Attacker Instruction", "").strip()
        entry["user_task_index"] = user_idx[u]
        entry["injection_task_index"] = inj_idx[a]
        annotated.append(entry)
    return annotated


def process(suite: str, setting: str) -> None:
    src = os.path.join(BENCHMARKS_DATA, f"test_cases_{suite}_{setting}.json")
    dst = os.path.join(OUT_DIR, f"test_cases_{suite}_{setting}.json")

    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    annotated = _annotate(data, suite, setting)

    with open(dst, "w", encoding="utf-8") as f:
        json.dump(annotated, f, indent=2, ensure_ascii=False)

    user_cat, inj_cat = _build_catalogs(data)
    print(
        f"  {suite}/{setting}: {len(annotated)} cases "
        f"({len(user_cat)} user tasks × {len(inj_cat)} injection tasks) → {dst}"
    )


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)

    for suite in ("dh", "ds"):
        print(f"=== {suite.upper()} ===")
        for setting in ("base", "enhanced"):
            process(suite, setting)

    print("\nDone. Feed these files into construct_attack.py, then run_topicattack_injecagent.py.")
