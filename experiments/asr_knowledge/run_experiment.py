#!/usr/bin/env python3
"""
run_experiment.py — General-purpose runner for the ASR knowledge-correlation experiment.

Usage:
    # Auto-derive output path (recommended)
    python run_experiment.py --config configs/suites/banking.json
    python run_experiment.py --config configs/suites/banking.json --workers 8

    # Explicit output path
    python run_experiment.py --config configs/banking_all_assets.json --output runs/test

    # Stage flags
    python run_experiment.py --config cfg.json --create-only
    python run_experiment.py --config cfg.json --test-only
    python run_experiment.py --config cfg.json --iterations 3 --workers 4

Output is written to:
    <output-root>/<suite>/<knowledge_label>/<defense_label>/
        payloads.json   — generated attack payloads
        results.json    — test outcomes with top-level ASR and utility_rate summary
        run.log         — human-readable execution log

Default output root: runs/asr_knowledge
"""

import argparse
import importlib
import json
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# --------------- PATH SETUP ---------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "benchmarks" / "agentdojo" / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

# --------------- IMPORTS ---------------
from general_attacker import (
    build_knowledge,
    call_attacker_llm,
    gather_tool_output,
    ALL_KNOWLEDGE_ASSET_IDS,
    build_knowledge_from_assets,
)
from benchmarks.agentdojo.src.api import AgentDojoChatSession

_SUITE_MODULE_MAP = {
    "banking":   "agentdojo.default_suites.v1.banking",
    "workspace": "agentdojo.default_suites.v1.workspace",
    "slack":     "agentdojo.default_suites.v1.slack",
    "travel":    "agentdojo.default_suites.v1.travel",
}

_SUITE_ATTR_MAP = {
    "banking":   "banking_task_suite",
    "workspace": "workspace_task_suite",
    "slack":     "slack_task_suite",
    "travel":    "travel_task_suite",
}

_DIV  = "=" * 80
_LINE = "─" * 80

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "runs" / "asr_knowledge"


# ---------------------------------------------------------------------------
# Output path derivation
# ---------------------------------------------------------------------------

def _derive_output_dir(config: dict, root: Path) -> Path:
    """Auto-derive output directory from config content."""
    triplets = config.get("triplets", [])
    suite = triplets[0][0] if triplets else "unknown"

    enabled = [k for k, v in config.get("knowledge_pieces", {}).items() if v]
    if not enabled:
        knowledge_label = "no_knowledge"
    elif len(enabled) == 1:
        knowledge_label = enabled[0]
    elif set(enabled) == set(ALL_KNOWLEDGE_ASSET_IDS):
        knowledge_label = "all_assets"
    else:
        knowledge_label = "multi__" + "__".join(sorted(enabled))

    defense = config.get("defense")
    defense_label = defense if defense else "no_defense"

    return root / suite / knowledge_label / defense_label


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class RunLogger:
    """Writes a human-readable log file and mirrors key lines to stdout.

    Thread-safe: all file writes are serialised with an internal lock.
    In parallel mode, callers collect log lines into a TripletLog and
    flush them in order after all workers finish (see _flush_triplet_log).
    """

    def __init__(self, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Append so a crash mid-run doesn't wipe the previous log; each run
        # header includes a timestamp so entries remain distinguishable.
        self._f = open(log_path, "a", encoding="utf-8")
        self._log_path = log_path
        self._lock = threading.Lock()

    def _write(self, text: str = ""):
        with self._lock:
            self._f.write(text + "\n")
            self._f.flush()

    def print(self, text: str = ""):
        with self._lock:
            print(text)
            self._f.write(text + "\n")
            self._f.flush()

    def header(self, config: dict, config_path: Path):
        enabled = [k for k, v in config.get("knowledge_pieces", {}).items() if v]
        self.print(_DIV)
        self.print("ASR KNOWLEDGE CORRELATION EXPERIMENT")
        self.print(f"Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.print(f"Config  : {config_path}")
        self.print(f"Attacker: {config.get('attacker_model', 'gpt-4o-2024-05-13')}")
        self.print(f"Target  : {config.get('target_model',   'gpt-4o-2024-05-13')}")
        self.print(f"Defense : {config.get('defense') or 'None'}")
        self.print(f"Assets  : {', '.join(enabled) if enabled else '(none)'}")
        self.print(_DIV)

    def triplet_header(self, index: int, total: int, suite: str, inj_task: str, user_task: str, attempt: int, max_attempts: int):
        self.print()
        label = f"[{index}/{total}] {suite} / {inj_task} / {user_task}"
        if max_attempts > 1:
            label += f"   (attempt {attempt}/{max_attempts})"
        self.print(label)
        self.print(_LINE)

    def log_payload(self, payload: str):
        self.print(f"PAYLOAD ({len(payload)} chars):")
        for line in payload.splitlines():
            self.print(f"  {line}")

    def log_conversation(self, messages):
        self.print()
        self.print("CONVERSATION:")
        for msg in messages:
            # Messages may be dicts or Pydantic models depending on the defense used.
            if hasattr(msg, "model_dump"):
                msg = msg.model_dump()
            elif not isinstance(msg, dict):
                self.print(f"  [?] {str(msg)[:200]}")
                continue
            role = msg.get("role", "?")
            content = msg.get("content")
            tool_call = msg.get("tool_call")

            if role == "system":
                text = _extract_text(content)
                self.print(f"  [system] {text[:200]}{'...' if len(text) > 200 else ''}")

            elif role == "user":
                text = _extract_text(content)
                self.print(f"  [user]   {text}")

            elif role == "assistant":
                if tool_call:
                    fn = getattr(tool_call, "function", None) or tool_call.get("function", "?")
                    args = getattr(tool_call, "args", None) or tool_call.get("args", {})
                    if hasattr(args, "model_dump"):
                        args = args.model_dump()
                    try:
                        args_str = json.dumps(args, ensure_ascii=False)
                    except Exception:
                        args_str = str(args)
                    self.print(f"  [assistant → {fn}({args_str})]")
                else:
                    text = _extract_text(content)
                    if text.strip():
                        self.print(f"  [assistant] {text}")

            elif role == "tool":
                tool_name = "tool"
                if tool_call:
                    fn = getattr(tool_call, "function", None) or tool_call.get("function", "?")
                    tool_name = fn
                text = _extract_text(content)
                if len(text) > 500:
                    text = text[:500] + f"  ... ({len(text) - 500} more chars)"
                self.print(f"  [tool: {tool_name}] {text}")

    def log_result(self, security: bool, utility: bool):
        attack_str  = "ATTACK ✓ SUCCESS " if security else "ATTACK ✗ FAILED  "
        utility_str = "UTILITY ✓ ACHIEVED" if utility  else "UTILITY ✗ FAILED "
        self.print()
        self.print(f"RESULT:  {attack_str}  |  {utility_str}")
        self.print(_LINE)

    def log_error(self, key: str, error: str):
        self.print()
        self.print(f"ERROR for {key}:")
        self.print(f"  {error}")
        self.print(_LINE)

    def summary(self, results: dict):
        # Exclude errored items from ASR calculation but report the count.
        errored = sum(1 for v in results.values() if v.get("error"))
        valid   = {k: v for k, v in results.items() if not v.get("error")}
        total   = len(results)
        attacks = sum(1 for v in valid.values() if v["security"])
        utility = sum(1 for v in valid.values() if v["utility"])
        asr     = attacks / len(valid) if valid else 0.0
        utr     = utility / len(valid) if valid else 0.0

        self.print()
        self.print(_DIV)
        self.print(f"SUMMARY  (finished {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
        self.print(_DIV)
        self.print(f"Triplets tested  : {total}")
        if errored:
            self.print(f"Errors (excluded): {errored}")
        self.print(f"Attack success   : {attacks}/{len(valid)}   ASR     = {asr:.1%}")
        self.print(f"Utility achieved : {utility}/{len(valid)}   Utility = {utr:.1%}")
        self.print(_DIV)

        return {
            "asr": round(asr, 4), "utility_rate": round(utr, 4),
            "attacks": attacks, "utility": utility,
            "total": total, "valid": len(valid), "errored": errored,
        }

    def close(self):
        self._f.close()
        print(f"[log] Saved → {self._log_path}")


def _flush_triplet_log(logger: RunLogger, idx: int, total: int, key: str, result: dict,
                       attempt: int = 1, max_attempts: int = 1):
    """Write one triplet's log block (used after parallel workers finish)."""
    suite_name, inj_id, user_id = key.split("/")
    logger.triplet_header(idx, total, suite_name, inj_id, user_id, attempt, max_attempts)
    if result.get("error"):
        logger.log_error(key, result["error"])
    else:
        logger.log_payload(result["payload"])
        logger.log_conversation(result["messages"])
        logger.log_result(result["security"], result["utility"])


def _extract_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("content") or block.get("text") or "")
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    return str(content)


# ---------------------------------------------------------------------------
# Suite loader
# ---------------------------------------------------------------------------

def _load_suite(suite_name: str):
    module_path = _SUITE_MODULE_MAP.get(suite_name)
    attr = _SUITE_ATTR_MAP.get(suite_name)
    if not module_path or not attr:
        raise ValueError(f"Unknown suite '{suite_name}'. Supported: {list(_SUITE_MODULE_MAP.keys())}")
    mod = importlib.import_module(module_path)
    return getattr(mod, attr)


def _uses_new_assets(knowledge_pieces_config: dict) -> bool:
    return any(k in ALL_KNOWLEDGE_ASSET_IDS for k in knowledge_pieces_config if knowledge_pieces_config[k])


# ---------------------------------------------------------------------------
# Atomic save helpers
# ---------------------------------------------------------------------------

def _atomic_save_json(data: dict, path: Path, encoder=None):
    """Write JSON to a temp file then rename atomically to avoid partial reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    kwargs: dict = {"indent": 2, "ensure_ascii": False}
    if encoder:
        kwargs["cls"] = encoder
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, **kwargs)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Payload generation
# ---------------------------------------------------------------------------

def generate_single_payload(config: dict, suite_name: str, injection_task_id: str, user_task_id: str, suite=None) -> str:
    if suite is None:
        suite = _load_suite(suite_name)

    knowledge_pieces_config = config["knowledge_pieces"]
    attacker_model = config.get("attacker_model", "gpt-4o-2024-05-13")
    target_model   = config.get("target_model",   "gpt-4o-2024-05-13")
    defense        = config.get("defense", None)

    injection_task = suite.get_injection_task_by_id(injection_task_id)
    user_task      = suite.get_user_task_by_id(user_task_id)
    malicious_goal = injection_task.GOAL

    if _uses_new_assets(knowledge_pieces_config):
        knowledge = build_knowledge_from_assets(
            asset_config=knowledge_pieces_config,
            suite=suite,
            injection_task=injection_task,
            user_task=user_task,
            target_model=target_model,
            defense_name=defense,
        )
        tool_output_for_llm = None
        if knowledge_pieces_config.get("injected_tool_output", False):
            from knowledge_gatherer import gather_injected_tool_output
            tool_output_for_llm = gather_injected_tool_output(suite, injection_task, user_task)
    else:
        tool_output = gather_tool_output(suite, injection_task, user_task)
        knowledge   = build_knowledge(
            knowledge_pieces_config=knowledge_pieces_config,
            suite=suite,
            injection_task=injection_task,
            user_task=user_task,
            tool_output=tool_output,
        )
        tool_output_for_llm = tool_output if knowledge_pieces_config.get("tool_output", False) else None

    return call_attacker_llm(
        malicious_goal=malicious_goal,
        knowledge=knowledge,
        model_name=attacker_model,
        tool_output=tool_output_for_llm,
    )


def generate_payloads(config: dict, output_path: Path, workers: int = 1) -> dict:
    triplets = config["triplets"]
    total = len(triplets)

    # Resume: load existing payloads so we only generate what's missing.
    payloads: dict[str, str] = {}
    if output_path.exists():
        try:
            with open(output_path, encoding="utf-8") as f:
                payloads = json.load(f)
            print(f"[generate] Resuming: {len(payloads)} payloads already saved.")
        except Exception as exc:
            print(f"[generate] Warning: could not load existing payloads ({exc}), starting fresh.")

    pending = [(i + 1, t) for i, t in enumerate(triplets)
               if f"{t[0]}/{t[1]}/{t[2]}" not in payloads]

    if not pending:
        print(f"[generate] All {total} payloads already exist, skipping generation.")
        return payloads

    print(f"[generate] {len(pending)}/{total} payloads to generate.")

    # Pre-load suites and warm up the registry before spawning threads.
    suite_names = {t[0] for _, t in pending}
    suite_cache = {name: _load_suite(name) for name in suite_names}
    if workers > 1:
        _warmup_suite_registry(suite_names)

    save_lock = threading.Lock()

    def _gen_one(args: tuple) -> tuple[str, str]:
        idx, triplet = args
        suite_name, inj_id, user_id = triplet
        key = f"{suite_name}/{inj_id}/{user_id}"
        print(f"[generate] ({idx}/{total}) {key}")
        try:
            payload = generate_single_payload(
                config=config,
                suite_name=suite_name,
                injection_task_id=inj_id,
                user_task_id=user_id,
                suite=suite_cache[suite_name],
            )
            print(f"  → {payload[:100]}{'...' if len(payload) > 100 else ''}")
        except Exception as exc:
            payload = f"[ERROR generating payload: {exc}]"
            print(f"  [!] Error for {key}: {exc}\n{traceback.format_exc()}")
        return key, payload

    if workers > 1:
        print(f"[generate] Running {len(pending)} payload generations with {workers} workers...")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_gen_one, a): a for a in pending}
            for future in as_completed(futures):
                try:
                    key, payload = future.result()
                except Exception as exc:
                    _, triplet = futures[future]
                    key = f"{triplet[0]}/{triplet[1]}/{triplet[2]}"
                    payload = f"[ERROR: {exc}]"
                    print(f"  [!] Unhandled error for {key}: {exc}")
                with save_lock:
                    payloads[key] = payload
                    _atomic_save_json(payloads, output_path)
    else:
        for a in pending:
            key, payload = _gen_one(a)
            payloads[key] = payload
            _atomic_save_json(payloads, output_path)

    print(f"[generate] {len(payloads)} payloads saved → {output_path}")
    return payloads


# ---------------------------------------------------------------------------
# Payload testing
# ---------------------------------------------------------------------------

def test_single_payload(
    suite_name: str,
    injection_task_id: str,
    user_task_id: str,
    payload: str,
    config: dict,
    logger: RunLogger | None = None,
    attempt: int = 1,
    max_attempts: int = 1,
    index: int = 1,
    total: int = 1,
) -> dict:
    target_model = config.get("target_model", "gpt-4o-2024-05-13")
    defense      = config.get("defense", None)

    if logger:
        logger.triplet_header(index, total, suite_name, injection_task_id, user_task_id, attempt, max_attempts)
        logger.log_payload(payload)

    session = AgentDojoChatSession(
        suite_name=suite_name,
        user_task_id=user_task_id,
        model_name=target_model,
        injection_task_name=injection_task_id,
        defense_name=defense,
    )
    messages, security, utility = session.inject_prompt_via_environment(payload)

    if logger:
        logger.log_conversation(messages)
        logger.log_result(security, utility)

    return {"payload": payload, "security": security, "utility": utility, "messages": messages}


def _warmup_suite_registry(suite_names: set[str]) -> None:
    """Force agentdojo's lazy suite registry to fully initialise in the calling
    thread before any workers are spawned.  load_suites._init_suites() sets its
    'already initialised' flag before its imports complete, so concurrent calls
    from multiple threads can race past the guard and see an empty registry."""
    from agentdojo.task_suite.load_suites import get_suite
    for name in suite_names:
        get_suite("v1", name)


def test_payloads(payloads_path: Path, output_path: Path, config: dict, logger: RunLogger | None = None, workers: int = 1) -> dict:
    with open(payloads_path, encoding="utf-8") as f:
        payloads = json.load(f)

    items = list(payloads.items())
    total = len(items)

    # Resume: load existing results so we only test what's missing.
    results: dict[str, dict] = {}
    if output_path.exists():
        try:
            with open(output_path, encoding="utf-8") as f:
                existing = json.load(f)
            # Only resume clean (non-errored) results; re-run errored ones.
            results = {k: v for k, v in existing.get("results", {}).items()
                       if not v.get("error")}
            if results:
                print(f"[test] Resuming: {len(results)}/{total} results already saved.")
        except Exception as exc:
            print(f"[test] Warning: could not load existing results ({exc}), starting fresh.")

    pending = [(i + 1, item) for i, item in enumerate(items) if item[0] not in results]

    if not pending:
        print(f"[test] All {total} results already exist.")
        summary_stats = logger.summary(results) if logger else _compute_summary(results)
        _save_results(results, summary_stats, output_path)
        return results

    print(f"[test] {len(pending)}/{total} tests to run.")

    save_lock = threading.Lock()

    def _save_incremental():
        summary = _compute_summary(results)
        _save_results(results, summary, output_path)

    if workers > 1:
        suite_names = {key.split("/")[0] for key, _ in items}
        _warmup_suite_registry(suite_names)
        print(f"[test] Running {len(pending)} tests with {workers} workers...")

        def _test_parallel(args: tuple) -> tuple[str, dict]:
            idx, (key, payload) = args
            suite_name, inj_id, user_id = key.split("/")
            try:
                result = test_single_payload(
                    suite_name=suite_name,
                    injection_task_id=inj_id,
                    user_task_id=user_id,
                    payload=payload,
                    config=config,
                    logger=None,
                    index=idx,
                    total=total,
                )
            except Exception as exc:
                tb = traceback.format_exc()
                result = {
                    "payload": payload, "security": False, "utility": False,
                    "messages": [], "error": f"{exc}\n{tb}",
                }
                print(f"  [!] Error for {key}: {exc}")
            status = f"attack={'✓' if result['security'] else '✗'} utility={'✓' if result['utility'] else '✗'}"
            if result.get("error"):
                status = "ERROR"
            print(f"  [{idx}/{total}] {key}: {status}")
            return key, result

        newly_computed: list[tuple[int, str]] = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_test_parallel, a): a for a in pending}
            for future in as_completed(futures):
                try:
                    key, result = future.result()
                except Exception as exc:
                    _, (key, payload) = futures[future]
                    tb = traceback.format_exc()
                    result = {
                        "payload": payload, "security": False, "utility": False,
                        "messages": [], "error": f"{exc}\n{tb}",
                    }
                    print(f"  [!] Unhandled error for {key}: {exc}")
                orig_idx = futures[future][0]
                newly_computed.append((orig_idx, key))
                with save_lock:
                    results[key] = result
                    _save_incremental()

        # Flush log for newly-computed items in original order.
        if logger:
            for orig_idx, key in sorted(newly_computed):
                _flush_triplet_log(logger, orig_idx, total, key, results[key])

    else:
        for idx, (key, payload) in pending:
            suite_name, inj_id, user_id = key.split("/")
            try:
                result = test_single_payload(
                    suite_name=suite_name,
                    injection_task_id=inj_id,
                    user_task_id=user_id,
                    payload=payload,
                    config=config,
                    logger=logger,
                    index=idx,
                    total=total,
                )
            except Exception as exc:
                tb = traceback.format_exc()
                error_msg = f"{exc}\n{tb}"
                print(f"  [!] Error for {key}: {exc}")
                if logger:
                    logger.log_error(key, error_msg)
                result = {
                    "payload": payload, "security": False, "utility": False,
                    "messages": [], "error": error_msg,
                }
            results[key] = result
            _save_incremental()

    summary_stats = logger.summary(results) if logger else _compute_summary(results)
    _save_results(results, summary_stats, output_path)
    return results


def run_with_iterations(config: dict, output_dir: Path, iterations: int, logger: RunLogger | None = None, workers: int = 1) -> dict:
    payloads_path = output_dir / "payloads.json"
    results_path  = output_dir / "results.json"
    output_dir.mkdir(parents=True, exist_ok=True)

    triplets = config["triplets"]
    total = len(triplets)

    # Resume: load existing results so we only run what's missing.
    final_results: dict[str, dict] = {}
    if results_path.exists():
        try:
            with open(results_path, encoding="utf-8") as f:
                existing = json.load(f)
            final_results = {k: v for k, v in existing.get("results", {}).items()
                             if not v.get("error")}
            if final_results:
                print(f"[iter] Resuming: {len(final_results)}/{total} results already saved.")
        except Exception as exc:
            print(f"[iter] Warning: could not load existing results ({exc}), starting fresh.")

    pending = [(i + 1, t) for i, t in enumerate(triplets)
               if f"{t[0]}/{t[1]}/{t[2]}" not in final_results]

    if not pending:
        print(f"[iter] All {total} results already exist.")
        summary_stats = logger.summary(final_results) if logger else _compute_summary(final_results)
        payloads_only = {k: v["payload"] for k, v in final_results.items()}
        _atomic_save_json(payloads_only, payloads_path)
        _save_results(final_results, summary_stats, results_path)
        return final_results

    # Pre-load suites and warm up the suite registry before spawning threads.
    suite_names = {t[0] for _, t in pending}
    suite_cache = {name: _load_suite(name) for name in suite_names}
    if workers > 1:
        _warmup_suite_registry(suite_names)

    save_lock = threading.Lock()

    def _save_incremental():
        summary = _compute_summary(final_results)
        payloads_only = {k: v["payload"] for k, v in final_results.items()}
        _atomic_save_json(payloads_only, payloads_path)
        _save_results(final_results, summary, results_path)

    def _run_triplet(args: tuple) -> tuple[int, str, dict]:
        idx, triplet = args
        suite_name, inj_id, user_id = triplet
        key = f"{suite_name}/{inj_id}/{user_id}"
        suite = suite_cache[suite_name]
        last_result = None
        for attempt in range(1, iterations + 1):
            try:
                payload = generate_single_payload(
                    config=config,
                    suite_name=suite_name,
                    injection_task_id=inj_id,
                    user_task_id=user_id,
                    suite=suite,
                )
            except Exception as exc:
                tb = traceback.format_exc()
                print(f"[iter] ({idx}/{total}) {key} attempt {attempt}/{iterations}: generation ERROR: {exc}")
                last_result = {
                    "payload": f"[ERROR generating: {exc}]", "security": False,
                    "utility": False, "messages": [], "error": f"{exc}\n{tb}",
                }
                break

            try:
                result = test_single_payload(
                    suite_name=suite_name,
                    injection_task_id=inj_id,
                    user_task_id=user_id,
                    payload=payload,
                    config=config,
                    logger=None,
                    attempt=attempt,
                    max_attempts=iterations,
                    index=idx,
                    total=total,
                )
            except Exception as exc:
                tb = traceback.format_exc()
                print(f"[iter] ({idx}/{total}) {key} attempt {attempt}/{iterations}: test ERROR: {exc}")
                last_result = {
                    "payload": payload, "security": False, "utility": False,
                    "messages": [], "error": f"{exc}\n{tb}",
                }
                break

            last_result = result
            status = f"attack={'✓' if result['security'] else '✗'}"
            print(f"[iter] ({idx}/{total}) {key} attempt {attempt}/{iterations}: {status}")
            if result["security"]:
                break

        return idx, key, last_result

    newly_computed: list[tuple[int, str]] = []

    if workers > 1:
        print(f"[iter] Running {len(pending)} triplets with {workers} workers (up to {iterations} attempts each)...")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_run_triplet, a): a for a in pending}
            for future in as_completed(futures):
                try:
                    idx, key, result = future.result()
                except Exception as exc:
                    orig_idx, triplet = futures[future]
                    key = f"{triplet[0]}/{triplet[1]}/{triplet[2]}"
                    tb = traceback.format_exc()
                    result = {
                        "payload": "[ERROR]", "security": False, "utility": False,
                        "messages": [], "error": f"{exc}\n{tb}",
                    }
                    idx = orig_idx
                    print(f"  [!] Unhandled error for {key}: {exc}")
                newly_computed.append((idx, key))
                with save_lock:
                    final_results[key] = result
                    _save_incremental()
    else:
        for a in pending:
            idx, key, result = _run_triplet(a)
            newly_computed.append((idx, key))
            final_results[key] = result
            _save_incremental()

    # Flush log for newly-computed items in original order.
    if logger:
        for orig_idx, key in sorted(newly_computed):
            _flush_triplet_log(logger, orig_idx, total, key, final_results[key],
                               attempt=1, max_attempts=iterations)

    summary_stats = logger.summary(final_results) if logger else _compute_summary(final_results)
    payloads_only = {k: v["payload"] for k, v in final_results.items()}
    _atomic_save_json(payloads_only, payloads_path)
    _save_results(final_results, summary_stats, results_path)
    return final_results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_summary(results: dict) -> dict:
    errored = sum(1 for v in results.values() if v.get("error"))
    valid   = [v for v in results.values() if not v.get("error")]
    total   = len(results)
    attacks = sum(1 for v in valid if v["security"])
    utility = sum(1 for v in valid if v["utility"])
    return {
        "asr":          round(attacks / len(valid), 4) if valid else 0.0,
        "utility_rate": round(utility / len(valid), 4) if valid else 0.0,
        "attacks":      attacks,
        "utility":      utility,
        "total":        total,
        "valid":        len(valid),
        "errored":      errored,
    }


class _PydanticEncoder(json.JSONEncoder):
    """JSON encoder that serialises Pydantic models at any nesting depth."""
    def default(self, obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return super().default(obj)


def _save_results(results: dict, summary_stats: dict, output_path: Path):
    """Save results.json with a prominent top-level summary block."""
    serialisable = {}
    for key, v in results.items():
        entry: dict = {
            "payload":  v["payload"],
            "security": v["security"],
            "utility":  v["utility"],
            "messages": list(v.get("messages") or []),
        }
        if v.get("error"):
            entry["error"] = v["error"]
        serialisable[key] = entry

    output = {"summary": summary_stats, "results": serialisable}
    _atomic_save_json(output, output_path, encoder=_PydanticEncoder)
    print(f"[results] Saved → {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ASR knowledge-correlation experiment runner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-derived output (recommended for organized storage)
  python run_experiment.py --config configs/suites/banking.json
  python run_experiment.py --config configs/suites/banking.json --workers 8

  # Explicit output path
  python run_experiment.py --config configs/suites/banking.json --output runs/test

  # Stage-only flags
  python run_experiment.py --config cfg.json --create-only
  python run_experiment.py --config cfg.json --test-only

  # Retry logic with parallel workers
  python run_experiment.py --config cfg.json --iterations 3 --workers 4
""")
    parser.add_argument("--config",       required=True,
                        help="Path to attack config JSON file.")
    parser.add_argument("--output",       default=None,
                        help="Explicit output directory. When omitted, path is auto-derived "
                             "from the config under --output-root.")
    parser.add_argument("--output-root",  default=str(DEFAULT_OUTPUT_ROOT),
                        help=f"Root directory for auto-derived output paths. "
                             f"Default: {DEFAULT_OUTPUT_ROOT}")
    parser.add_argument("--workers",      type=int, default=1,
                        help="Number of parallel workers for payload generation and testing. "
                             "Default: 1 (sequential).")
    parser.add_argument("--create-only",  action="store_true",
                        help="Only generate payloads; skip testing.")
    parser.add_argument("--test-only",    action="store_true",
                        help="Only test existing payloads; skip generation.")
    parser.add_argument("--iterations",   type=int, default=1,
                        help="Retry failed attacks up to N times per triplet (default: 1).")
    args = parser.parse_args()

    config_path = Path(args.config)
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = _derive_output_dir(config, Path(args.output_root))
        print(f"[output] Auto-derived: {output_dir}")

    payloads_path = output_dir / "payloads.json"
    results_path  = output_dir / "results.json"
    log_path      = output_dir / "run.log"

    logger = RunLogger(log_path)
    logger.header(config, config_path)

    if args.workers > 1:
        logger.print(f"Workers : {args.workers} (parallel)")

    try:
        if args.iterations > 1:
            run_with_iterations(config, output_dir, args.iterations, logger=logger, workers=args.workers)
            return

        if not args.test_only:
            generate_payloads(config, payloads_path, workers=args.workers)

        if not args.create_only:
            if not payloads_path.exists():
                print(f"[error] payloads.json not found at {payloads_path}. Run without --test-only first.")
                sys.exit(1)
            test_payloads(payloads_path, results_path, config, logger=logger, workers=args.workers)
    finally:
        logger.close()


if __name__ == "__main__":
    main()
