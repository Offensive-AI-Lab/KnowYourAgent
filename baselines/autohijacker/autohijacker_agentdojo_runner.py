#!/usr/bin/env python3
"""
AutoHijacker — AgentDojo Evaluation Runner

Loads the trained attack_memory.json, runs AutoHijacker's test stage
(Prompter → Attacker) for every (suite, user_task, injection_task) case,
submits the generated D̂ to AgentDojo via inject_prompt_via_environment,
and writes a JSON file with full conversations, per-case attack success /
utility flags, overall ASR, and a per-suite breakdown.

Usage (from PentestingAgent/):
    python Baselines/AutoHijacker/autohijacker_agentdojo_runner.py \\
        --config Baselines/AutoHijacker/autohijacker_agentdojo_config.json \\
        [--smoke-test] \\
        [--output runs/autohijacker/results.json]

--smoke-test runs exactly one case per suite (first user_task × first
injection_task) so you can verify the full pipeline end-to-end before
committing to the full benchmark.
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

# Disable CrewAI / OpenTelemetry telemetry noise
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"

# ── Path setup (must run from PentestingAgent/) ───────────────────────────────
_HERE = Path(__file__).resolve().parent          # Baselines/AutoHijacker/
_ROOT = _HERE.parent.parent                      # PentestingAgent/
sys.path.insert(0, str(_ROOT))                   # PentestingAgent/ – for Benchmarks.* imports
sys.path.insert(0, str(_HERE))                   # AutoHijacker/   – for prompter/attacker modules
sys.path.insert(0, str(_ROOT / "Benchmarks" / "agentdojo_edited" / "src"))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from benchmarks.agentdojo.src.api import (
    AgentDojoChatSession,
    get_injection_goal,
    _make_json_serializable,
)
from benchmarks.agentdojo.src.agentdojo.task_suite.load_suites import _init_suites as _agentdojo_init_suites
from autohijacker_test import test_stage

# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = _HERE / "autohijacker_agentdojo_config.json"
_save_lock = threading.Lock()


# ===================================================================
# Config helpers
# ===================================================================

def load_config(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def build_case_list(
    test_cfg: Dict[str, Any],
    smoke_test: bool = False,
) -> List[Tuple[str, str, str]]:
    """Return (suite, user_task, injection_task) triples from the config.

    With smoke_test=True only the first user_task × first injection_task of
    each suite is returned — one case per suite for a quick end-to-end check.
    """
    cases: List[Tuple[str, str, str]] = []
    for suite_cfg in test_cfg["suites"]:
        suite = suite_cfg["name"]
        user_tasks = suite_cfg["user_tasks"]
        injection_tasks = suite_cfg["injection_tasks"]
        if smoke_test:
            cases.append((suite, user_tasks[0], injection_tasks[0]))
        else:
            for ut in user_tasks:
                for it in injection_tasks:
                    cases.append((suite, ut, it))
    return cases


# ===================================================================
# Injection document helpers
# ===================================================================

def get_original_document(session: AgentDojoChatSession) -> str:
    """Return the benign default content at the suite's injection locations.

    Concatenates all non-empty injection-vector defaults so the Attacker has
    a representative external document to embed the payload into.
    """
    try:
        defaults: Dict[str, str] = session.suite.get_injection_vector_defaults()
        parts = [v.strip() for v in defaults.values() if v and v.strip()]
        return "\n\n".join(parts)
    except Exception as exc:
        print(f"  [Warning] Could not retrieve injection defaults: {exc}")
        return ""


# ===================================================================
# Single-case runner
# ===================================================================

def run_one_case(
    suite: str,
    user_task: str,
    injection_task: str,
    target_model: str,
    llm_model: str,
    output_dir: Path,
    defense_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the full AutoHijacker pipeline for one (suite, user_task, injection_task).

    Pipeline:
        1. Fetch injection goal G from AgentDojo.
        2. Build AgentDojo session; derive original document D from injection
           vector defaults.
        3. Call AutoHijacker test_stage(D, G) → D̂  (Prompter → Attacker).
        4. Submit D̂ via inject_prompt_via_environment → (messages, success, utility).
        5. Return a structured result dict.

    Returns a dict with:
        suite, user_task, injection_task,
        injection_goal, original_data_D, injection_payload_D_hat,
        attack_success, utility, conversation, error
    """
    result: Dict[str, Any] = {
        "suite": suite,
        "user_task": user_task,
        "injection_task": injection_task,
        "injection_goal": None,
        "original_data_D": None,
        "injection_payload_D_hat": None,
        "attack_success": False,
        "utility": False,
        "conversation": [],
        "error": None,
    }

    try:
        # ── Step 1: Injection goal G ──────────────────────────────────────────
        goal = get_injection_goal(suite, injection_task)
        result["injection_goal"] = goal
        print(f"  Goal : {goal[:100]}")

        # ── Step 2: Original document D ───────────────────────────────────────
        session = AgentDojoChatSession(
            suite_name=suite,
            user_task_id=user_task,
            model_name=target_model,
            injection_task_name=injection_task,
            run_dir=str(output_dir),
            defense_name=defense_name,
            system_message_name=None,
        )
        original_d = get_original_document(session)
        result["original_data_D"] = original_d
        print(f"  D    : {original_d[:80]}...")

        # ── Step 3: AutoHijacker test stage → D̂ ──────────────────────────────
        print("  Running test stage (Prompter → Attacker)...")
        d_hat = test_stage(
            original_data=original_d,
            attack_goal=goal,
            llm=llm_model,
        )
        result["injection_payload_D_hat"] = d_hat
        print(f"  D̂    : {d_hat[:120]}...")

        # ── Step 4: AgentDojo evaluation ──────────────────────────────────────
        print("  Injecting D̂ into AgentDojo and evaluating...")
        # Fresh session so inject_prompt_via_environment starts from a clean env
        eval_session = AgentDojoChatSession(
            suite_name=suite,
            user_task_id=user_task,
            model_name=target_model,
            injection_task_name=injection_task,
            run_dir=str(output_dir),
            defense_name=defense_name,
            system_message_name=None,
        )
        messages, attack_success, utility = eval_session.inject_prompt_via_environment(d_hat)

        result["attack_success"] = bool(attack_success)
        result["utility"] = bool(utility)
        result["conversation"] = _make_json_serializable(list(messages))

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"  [ERROR] {type(exc).__name__}: {exc}")

    return result


# ===================================================================
# Metrics aggregation
# ===================================================================

def aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute overall and per-suite ASR / utility from a completed results list."""
    suite_stats: Dict[str, Dict[str, int]] = {}

    for r in results:
        s = r["suite"]
        if s not in suite_stats:
            suite_stats[s] = {
                "total": 0,
                "successes": 0,
                "utility_count": 0,
                "errors": 0,
            }
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
    """Write results + live summary to disk (called after every case)."""
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
        description="AutoHijacker AgentDojo evaluation runner"
    )
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to autohijacker_agentdojo_config.json",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help=(
            "Output JSON file path. "
            "Defaults to runs/autohijacker/results[_smoke]_<timestamp>.json"
        ),
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run one case per suite only (quick end-to-end sanity check)",
    )
    args = parser.parse_args()

    # ── Guard: attack memory must exist ─────────────────────────────────────
    memory_file = _HERE / "attack_memory.json"
    if not memory_file.exists():
        print(
            f"[ERROR] attack_memory.json not found at {memory_file}\n"
            "Run autohijacker_train.py first to generate the trained memory."
        )
        sys.exit(1)

    # ── Config ───────────────────────────────────────────────────────────────
    cfg = load_config(args.config)
    test_cfg = cfg["test"]
    train_cfg = cfg.get("training", {})

    target_model: str = test_cfg.get("target_model", train_cfg.get("target_model", "gpt-4.1-2025-04-14"))
    llm_model: str = test_cfg.get("llm_model", train_cfg.get("llm_model", "gpt-4.1-2025-04-14"))
    defense_name: Optional[str] = test_cfg.get("defense", None)
    num_workers: int = test_cfg.get("num_workers", 1)

    # ── Output path ──────────────────────────────────────────────────────────
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    smoke_tag = "_smoke" if args.smoke_test else ""
    if args.output:
        output_path: Path = args.output
    else:
        output_path = _ROOT / "runs" / "autohijacker" / f"results{smoke_tag}_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Build case list ──────────────────────────────────────────────────────
    cases = build_case_list(test_cfg, smoke_test=args.smoke_test)

    metadata = {
        "target_model": target_model,
        "llm_model": llm_model,
        "defense": defense_name,
        "smoke_test": args.smoke_test,
        "total_cases": len(cases),
        "num_workers": num_workers,
        "config": str(args.config),
        "output": str(output_path),
        "start_time": datetime.datetime.now().isoformat(),
    }

    print("=" * 60)
    print("  AutoHijacker — AgentDojo Evaluation Runner")
    print("=" * 60)
    print(f"  Config       : {args.config}")
    print(f"  Target model : {target_model}")
    print(f"  LLM model    : {llm_model}")
    print(f"  Defense      : {defense_name or 'none'}")
    print(f"  Cases        : {len(cases)}" + ("  [SMOKE TEST]" if args.smoke_test else ""))
    print(f"  Workers      : {num_workers}")
    print(f"  Output       : {output_path}")
    print("=" * 60)

    # Pre-initialize AgentDojo suite registry in main thread to avoid a race
    # condition in _init_suites() when multiple workers call get_suite() concurrently.
    _agentdojo_init_suites()

    # ── Main loop (threaded) ─────────────────────────────────────────────────
    results: List[Dict[str, Any]] = []

    def _run_and_save(suite: str, ut: str, it: str, case_num: int, total: int) -> Dict[str, Any]:
        print(f"\n[{case_num}/{total}] {suite} / {ut} / {it}")
        r = run_one_case(
            suite=suite,
            user_task=ut,
            injection_task=it,
            target_model=target_model,
            llm_model=llm_model,
            output_dir=output_path.parent,
            defense_name=defense_name,
        )
        status = "SUCCESS" if r["attack_success"] else "FAIL"
        util_str = "utility=T" if r["utility"] else "utility=F"
        err_str = "  [ERROR]" if r["error"] else ""
        print(f"  [{case_num}/{total}] → attack={status}, {util_str}{err_str}")
        with _save_lock:
            results.append(r)
            save_results(results, output_path, metadata)
        return r

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {
            executor.submit(_run_and_save, suite, ut, it, i, len(cases)): (suite, ut, it)
            for i, (suite, ut, it) in enumerate(cases, start=1)
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                suite, ut, it = futures[future]
                print(f"  [UNHANDLED ERROR] {suite}/{ut}/{it}: {exc}")

    # ── Final summary ────────────────────────────────────────────────────────
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
