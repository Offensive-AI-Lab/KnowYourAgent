"""
Driver: runs ChatInject multi-turn-7 attack on one AgentDojo suite.

Uses Or's AgentDojoChatSession (Benchmarks/agentdojo_edited/src/api.py) — the
canonical single-session interface for prompt-injection experiments in this
project. Iterates over all (user_task, injection_task) pairs in the suite,
calling session.inject_prompt_via_environment(payload) with a payload built
by chatinject.payload.build_payload.

Writes one JSON file per attempt to the output directory.
"""

import argparse
import json
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

from benchmarks.agentdojo.src.api import AgentDojoChatSession  # type: ignore
from agentdojo.task_suite.load_suites import get_suite
from baselines.static.chatinject.payload import build_payload


_DEFENSE_CHOICES = (
    "none",
    "transformers_pi_detector",
    "repeat_user_prompt",
    "spotlighting_with_delimiting",
)


def _serialize_pi_detector_construction() -> None:
    """Wrap TransformersBasedPIDetector.__init__ in a process-wide lock.

    Concurrent calls to transformers' pipeline() across many threads race on
    HuggingFace's lazy-loading machinery and surface as
    `NotImplementedError: Cannot copy out of meta tensor`. Serializing the
    constructor (which is where pipeline() is called) eliminates the race
    without hurting inference parallelism — detect() calls on the loaded
    pipeline stay concurrent.
    """
    from agentdojo.agent_pipeline.pi_detector import TransformersBasedPIDetector

    if getattr(TransformersBasedPIDetector, "_init_serialized", False):
        return

    orig_init = TransformersBasedPIDetector.__init__
    lock = threading.Lock()

    def _locked_init(self, *args, **kwargs):
        with lock:
            return orig_init(self, *args, **kwargs)

    TransformersBasedPIDetector.__init__ = _locked_init
    TransformersBasedPIDetector._init_serialized = True


def _run_one(suite_name: str, user_task_id: str, injection_task_id: str,
             model: str, out_dir: Path, defense: str = "none") -> dict[str, Any]:
    """Run one (suite, user_task, injection_task) attempt and write the result JSON."""
    out_path = out_dir / f"{user_task_id}__{injection_task_id}.json"
    if out_path.exists():
        with open(out_path) as f:
            return json.load(f)

    record: dict[str, Any] = {
        "suite": suite_name,
        "user_task_id": user_task_id,
        "injection_task_id": injection_task_id,
        "model": model,
        "defense": defense,
        "ts_start": time.time(),
    }

    try:
        payload = build_payload(suite_name, injection_task_id)
    except KeyError as e:
        record["status"] = "no_dialogue"
        record["error"] = str(e)
        out_path.write_text(json.dumps(record, indent=2))
        return record

    defense_name = None if defense == "none" else defense
    try:
        session = AgentDojoChatSession(
            suite_name=suite_name,
            user_task_id=user_task_id,
            model_name=model,
            injection_task_name=injection_task_id,
            run_dir=str(out_dir / "_session_logs"),
            defense_name=defense_name,
        )
        # _get_injection_candidates may raise ValueError if the task isn't
        # injectable for this user_task. Catch and record.
        try:
            candidates = session._get_injection_candidates()
        except ValueError as e:
            record["status"] = "not_injectable"
            record["error"] = str(e)
            out_path.write_text(json.dumps(record, indent=2))
            return record

        record["injection_candidates"] = candidates

        messages, security, utility = session.inject_prompt_via_environment(payload)
        record["status"] = "ok"
        record["security"] = bool(security)
        record["utility"] = bool(utility)
        record["payload_len"] = len(payload)
        # Persist full conversation messages to a sibling file (can be large).
        messages_path = out_dir / f"{user_task_id}__{injection_task_id}.messages.json"
        messages_path.write_text(json.dumps(_serialize_messages(messages), indent=2))
        record["messages_path"] = messages_path.name
    except Exception as e:
        record["status"] = "error"
        record["error"] = f"{type(e).__name__}: {e}"
        record["traceback"] = traceback.format_exc()
    finally:
        record["ts_end"] = time.time()
        record["duration_s"] = record["ts_end"] - record["ts_start"]
        out_path.write_text(json.dumps(record, indent=2))
    return record


def _to_jsonable(obj):
    """Recursively convert Pydantic / FunctionCall / dataclass-ish objects to JSON-safe types."""
    if hasattr(obj, "model_dump"):
        return _to_jsonable(obj.model_dump())
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _serialize_messages(messages):
    return _to_jsonable(list(messages))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True, choices=["banking", "slack", "travel", "workspace"])
    ap.add_argument("--model", required=True, help="e.g. gpt-4.1-2025-04-14 or gpt-4o-mini-2024-07-18")
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--max-workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None,
                    help="If set, run only the first N (user_task × injection_task) pairs.")
    ap.add_argument("--defense", choices=_DEFENSE_CHOICES, default="none",
                    help="AgentDojo defense_name to pass to AgentDojoChatSession. "
                         "'none' (default) keeps the baseline. Other values map directly "
                         "to entries in agentdojo.agent_pipeline.agent_pipeline.DEFENSES.")
    args = ap.parse_args()

    print(f"[run_chatinject] MODEL = {args.model!r}", flush=True)
    print(f"[run_chatinject] SUITE = {args.suite}", flush=True)
    print(f"[run_chatinject] OUTPUT = {args.output_dir}", flush=True)
    print(f"[run_chatinject] MAX_WORKERS = {args.max_workers}", flush=True)
    print(f"[run_chatinject] DEFENSE = {args.defense!r} "
          f"(defense_name passed to AgentDojoChatSession: "
          f"{None if args.defense == 'none' else args.defense!r})", flush=True)

    if args.defense == "transformers_pi_detector":
        _serialize_pi_detector_construction()
        print("[run_chatinject] TransformersBasedPIDetector.__init__ serialized "
              "(prevents meta-tensor race with multi-threaded workers).", flush=True)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    suite = get_suite("v1", args.suite)
    user_task_ids = sorted(suite.user_tasks.keys())
    injection_task_ids = sorted(suite.injection_tasks.keys())
    pairs = [(u, i) for u in user_task_ids for i in injection_task_ids]
    if args.limit is not None:
        pairs = pairs[:args.limit]
    print(f"[run_chatinject] Pairs to run: {len(pairs)} ({len(user_task_ids)} user × {len(injection_task_ids)} injection)", flush=True)

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {
            pool.submit(_run_one, args.suite, u, i, args.model, args.output_dir, args.defense): (u, i)
            for (u, i) in pairs
        }
        done = 0
        for fut in as_completed(futures):
            u, i = futures[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = {"suite": args.suite, "user_task_id": u, "injection_task_id": i,
                       "status": "fatal", "error": f"{type(e).__name__}: {e}"}
            results.append(rec)
            done += 1
            status = rec.get("status", "?")
            sec = rec.get("security", "n/a")
            print(f"[{done:>4}/{len(pairs)}] {u} × {i}: status={status} security={sec}", flush=True)

    # Summary
    ok = [r for r in results if r.get("status") == "ok"]
    asr = sum(1 for r in ok if r.get("security")) / max(len(ok), 1) * 100
    print(f"\n[run_chatinject] DONE. ok={len(ok)}/{len(results)}, ASR={asr:.2f}% (over ok results)")
    print(f"[run_chatinject] not_injectable={sum(1 for r in results if r.get('status')=='not_injectable')}")
    print(f"[run_chatinject] no_dialogue={sum(1 for r in results if r.get('status')=='no_dialogue')}")
    print(f"[run_chatinject] error={sum(1 for r in results if r.get('status')=='error')}")


if __name__ == "__main__":
    main()
