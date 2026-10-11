#!/usr/bin/env python3
"""
AutoHijacker — InjecAgent Evaluation Runner

Loads the trained attack_memory.json, runs AutoHijacker's test stage
(Prompter → Attacker) for every (suite, user_task_index, injection_task_index)
case across the dh and ds InjecAgent suites, submits the generated D̂ via
inject_at_tool_message, and writes a JSON file with full per-case results,
per-suite ASR / utility, and overall totals.

Usage (from PentestingAgent/):
    python Baselines/AutoHijacker/autohijacker_injecagent_runner.py \\
        --config Baselines/AutoHijacker/autohijacker_injecagent_config.json \\
        [--smoke-test] \\
        [--output runs/autohijacker_injecagent/results.json]

--smoke-test runs exactly one case per suite (dh + ds) for a quick end-to-end
sanity check before committing to the full 1054-case run.

Note on utility: InjecAgent's API defines utility_bool = security_bool
(a simplification in the benchmark — utility is not independently tracked).
"""

import os
import sys
import json
import argparse
import datetime
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"

_HERE = Path(__file__).resolve().parent          # Baselines/AutoHijacker/
_ROOT = _HERE.parent.parent                      # PentestingAgent/
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_HERE))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from benchmarks.injecagent.src.api import InjecAgentChatSession
from autohijacker_test import test_stage

DEFAULT_CONFIG = _HERE / "autohijacker_injecagent_config.json"
_save_lock = threading.Lock()


# ===================================================================
# Case list helpers
# ===================================================================

def build_case_list(
    suites: List[str],
    setting: str,
    data_dir: str,
    smoke_test: bool = False,
) -> List[Tuple[str, int, int]]:
    """Return (suite, user_task_index, injection_task_index) triples.

    Iterates the actual data files to enumerate only pairs that have a
    matching intersection case, avoiding RuntimeErrors from the session.
    With smoke_test=True, returns one case per suite.
    """
    cases: List[Tuple[str, int, int]] = []
    for suite in suites:
        fname = f"test_cases_{suite}_{setting}.json"
        fpath = os.path.join(data_dir, fname)
        with open(fpath, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        # Build deterministic catalogs (same logic as InjecAgentChatSession)
        user_catalog: List[str] = []
        inj_catalog: List[str] = []
        seen_u: set = set()
        seen_i: set = set()
        for item in data:
            u = item.get("User Instruction", "").strip()
            a = item.get("Attacker Instruction", "").strip()
            if u not in seen_u:
                seen_u.add(u)
                user_catalog.append(u)
            if a not in seen_i:
                seen_i.add(a)
                inj_catalog.append(a)

        u_index = {u: i for i, u in enumerate(user_catalog)}
        a_index = {a: i for i, a in enumerate(inj_catalog)}

        # Collect valid (u_idx, a_idx) pairs that exist in the data
        valid: set = set()
        for item in data:
            u = item.get("User Instruction", "").strip()
            a = item.get("Attacker Instruction", "").strip()
            if u in u_index and a in a_index:
                valid.add((u_index[u], a_index[a]))

        sorted_pairs = sorted(valid)
        if smoke_test:
            sorted_pairs = sorted_pairs[:1]

        for u_idx, a_idx in sorted_pairs:
            cases.append((suite, u_idx, a_idx))

    return cases


# ===================================================================
# Single-case runner
# ===================================================================

def run_one_case(
    suite: str,
    user_idx: int,
    inj_idx: int,
    target_model: str,
    llm_model: str,
    output_dir: Path,
) -> Dict[str, Any]:
    """Run the full AutoHijacker pipeline for one InjecAgent case.

    Pipeline:
        1. Create InjecAgentChatSession → loads dataset, selects intersection case.
        2. Call init_chat() to populate history (required before inject_at_tool_message).
        3. Extract D (benign Tool Response) and G (Attacker Instruction) from the case.
        4. Call test_stage(D, G) → D̂  (Prompter → Attacker).
        5. Call inject_at_tool_message(D̂) → evaluate victim model.
        6. Parse attack_success and utility from return strings.
    """
    result: Dict[str, Any] = {
        "suite": suite,
        "user_task_index": user_idx,
        "injection_task_index": inj_idx,
        "attack_goal": None,
        "original_data_D": None,
        "injection_payload_D_hat": None,
        "attack_success": False,
        "utility": False,
        "conversation": [],
        "error": None,
    }

    try:
        # ── Step 1: Create session ────────────────────────────────────────────
        session = InjecAgentChatSession(
            suite_name=suite,
            user_task_id=str(user_idx),
            model_name=target_model,
            injection_task_name=str(inj_idx),
            run_dir=str(output_dir),
        )

        selected = session._selected_item
        D = selected.get("Tool Response", "")
        G = selected.get("Attacker Instruction", "")
        result["attack_goal"] = G
        result["original_data_D"] = D
        print(f"  Goal : {G[:100]}")
        print(f"  D    : {D[:80]}...")

        # ── Step 2: Populate history (required before inject_at_tool_message) ─
        session.init_chat()

        # ── Step 3: AutoHijacker test stage → D̂ ──────────────────────────────
        print("  Running test stage (Prompter → Attacker)...")
        d_hat = test_stage(
            original_data=D,
            attack_goal=G,
            llm=llm_model,
        )
        result["injection_payload_D_hat"] = d_hat
        print(f"  D̂    : {d_hat[:120]}...")

        # ── Step 4: Inject and evaluate ───────────────────────────────────────
        print("  Injecting D̂ into InjecAgent and evaluating...")
        history, success_str, utility_str = session.inject_at_tool_message(d_hat)

        attack_success = "True" in success_str
        utility = "True" in utility_str
        result["attack_success"] = attack_success
        result["utility"] = utility
        result["conversation"] = [
            {"role": m.get("role"), "content": str(m.get("content", ""))}
            for m in (history if isinstance(history, list) else [])
        ]

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"  [ERROR] {type(exc).__name__}: {exc}")

    return result


# ===================================================================
# Metrics aggregation
# ===================================================================

def aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    suite_stats: Dict[str, Dict[str, int]] = {}

    for r in results:
        s = r["suite"]
        if s not in suite_stats:
            suite_stats[s] = {"total": 0, "successes": 0, "utility_count": 0, "errors": 0}
        suite_stats[s]["total"] += 1
        if r.get("attack_success"):
            suite_stats[s]["successes"] += 1
        if r.get("utility"):
            suite_stats[s]["utility_count"] += 1
        if r.get("error"):
            suite_stats[s]["errors"] += 1

    total = sum(v["total"] for v in suite_stats.values())
    total_successes = sum(v["successes"] for v in suite_stats.values())
    total_utility = sum(v["utility_count"] for v in suite_stats.values())
    total_errors = sum(v["errors"] for v in suite_stats.values())

    by_suite: Dict[str, Any] = {}
    for suite_name, s in suite_stats.items():
        n = s["total"]
        by_suite[suite_name] = {
            "total": n,
            "successes": s["successes"],
            "utility_count": s["utility_count"],
            "errors": s["errors"],
            "asr": round(s["successes"] / n, 4) if n else 0.0,
            "utility_rate": round(s["utility_count"] / n, 4) if n else 0.0,
        }

    return {
        "total_cases": total,
        "total_successes": total_successes,
        "total_utility": total_utility,
        "total_errors": total_errors,
        "overall_asr": round(total_successes / total, 4) if total else 0.0,
        "overall_utility_rate": round(total_utility / total, 4) if total else 0.0,
        "by_suite": by_suite,
    }


# ===================================================================
# Persistence
# ===================================================================

def save_results(
    results: List[Dict[str, Any]],
    output_path: Path,
    metadata: Dict[str, Any],
) -> None:
    summary = aggregate(results)
    payload = {
        "metadata": {
            **metadata,
            "cases_completed": len(results),
            "last_updated": datetime.datetime.now().isoformat(),
        },
        "summary": summary,
        "results": results,
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


# ===================================================================
# Main
# ===================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AutoHijacker InjecAgent evaluation runner"
    )
    parser.add_argument("--config", "-c", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", "-o", type=Path, default=None)
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run one case per suite (dh + ds) for quick end-to-end check",
    )
    args = parser.parse_args()

    memory_file = _HERE / "attack_memory.json"
    if not memory_file.exists():
        print(
            f"[ERROR] attack_memory.json not found at {memory_file}\n"
            "Run autohijacker_train.py first to generate the trained memory."
        )
        sys.exit(1)

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    test_cfg = cfg["test"]

    target_model: str = test_cfg.get("target_model", "gpt-4o-2024-05-13")
    llm_model: str = test_cfg.get("llm_model", "gpt-4o-mini")
    setting: str = test_cfg.get("setting", "enhanced")
    suites: List[str] = test_cfg.get("suites", ["dh", "ds"])
    data_dir: str = test_cfg.get("data_dir", "Benchmarks/injecagent/data")
    num_workers: int = test_cfg.get("num_workers", 10)

    # Resolve data_dir relative to repo root
    data_dir_path = _ROOT / data_dir if not os.path.isabs(data_dir) else Path(data_dir)

    # Set InjecAgentChatSession env vars before spawning threads
    os.environ["SETTING"] = setting
    os.environ["MODEL_NAME"] = target_model
    os.environ["MODEL_TYPE"] = "GPT"

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    smoke_tag = "_smoke" if args.smoke_test else ""
    if args.output:
        output_path: Path = args.output
    else:
        output_path = _ROOT / "runs" / "autohijacker_injecagent" / f"results{smoke_tag}_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cases = build_case_list(suites, setting, str(data_dir_path), smoke_test=args.smoke_test)

    metadata = {
        "target_model": target_model,
        "llm_model": llm_model,
        "setting": setting,
        "suites": suites,
        "smoke_test": args.smoke_test,
        "total_cases": len(cases),
        "num_workers": num_workers,
        "config": str(args.config),
        "output": str(output_path),
        "start_time": datetime.datetime.now().isoformat(),
    }

    print("=" * 60)
    print("  AutoHijacker — InjecAgent Evaluation Runner")
    print("=" * 60)
    print(f"  Config       : {args.config}")
    print(f"  Setting      : {setting}")
    print(f"  Suites       : {suites}")
    print(f"  Target model : {target_model}")
    print(f"  LLM model    : {llm_model}")
    print(f"  Cases        : {len(cases)}" + ("  [SMOKE TEST]" if args.smoke_test else ""))
    print(f"  Workers      : {num_workers}")
    print(f"  Output       : {output_path}")
    print("=" * 60)

    results: List[Dict[str, Any]] = []
    completed_count = 0

    def _run_and_save(suite: str, u_idx: int, a_idx: int, case_num: int, total: int) -> Dict[str, Any]:
        nonlocal completed_count
        print(f"\n[{case_num}/{total}] {suite} / user={u_idx} / inj={a_idx}")
        r = run_one_case(
            suite=suite,
            user_idx=u_idx,
            inj_idx=a_idx,
            target_model=target_model,
            llm_model=llm_model,
            output_dir=output_path.parent,
        )
        status = "SUCCESS" if r["attack_success"] else "FAIL"
        util_str = "utility=T" if r["utility"] else "utility=F"
        err_str = "  [ERROR]" if r["error"] else ""
        print(f"  [{case_num}/{total}] → attack={status}, {util_str}{err_str}")

        with _save_lock:
            results.append(r)
            completed_count += 1
            save_results(results, output_path, metadata)

        return r

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {
            executor.submit(_run_and_save, suite, u_idx, a_idx, i, len(cases)): (suite, u_idx, a_idx)
            for i, (suite, u_idx, a_idx) in enumerate(cases, start=1)
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                suite, u_idx, a_idx = futures[future]
                print(f"  [UNHANDLED ERROR] {suite}/user={u_idx}/inj={a_idx}: {exc}")

    summary = aggregate(results)
    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)
    print(
        f"  Overall ASR     : {summary['overall_asr']:.1%}"
        f"  ({summary['total_successes']}/{summary['total_cases']})"
    )
    print(
        f"  Overall Utility : {summary['overall_utility_rate']:.1%}"
        f"  ({summary['total_utility']}/{summary['total_cases']})"
    )
    if summary["total_errors"]:
        print(f"  Errors          : {summary['total_errors']}")
    print()
    for suite_name, s in summary["by_suite"].items():
        print(
            f"  {suite_name:10s}  "
            f"ASR={s['asr']:.1%} ({s['successes']}/{s['total']})  "
            f"utility={s['utility_rate']:.1%} ({s['utility_count']}/{s['total']})"
        )
    print("=" * 60)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
