"""Run a list of pentests sequentially or in parallel, with per-run logs and a results file.

Every entry point (``run_agentdojo``, ``run_injecagent``, ``run_openhands``)
hands its config entries to :func:`run_all`. Each run gets its own log file;
one JSON line per finished run is appended to ``results.jsonl`` so that ASR can
be computed without parsing logs (see ``python -m kya.summarize``).
"""
from __future__ import annotations

import json
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from kya.runlog import run_log


def add_runner_arguments(parser) -> None:
    parser.add_argument("-c", "--config", required=True,
                        help="Path to a JSON file containing a list of run settings.")
    parser.add_argument("-o", "--output-dir", default=None,
                        help="Directory for logs and results.jsonl. Overrides the 'log_file' of every config entry.")
    parser.add_argument("-w", "--workers", type=int, default=1,
                        help="Number of runs to execute in parallel (one process per run). Default: 1.")
    parser.add_argument("--resume", action="store_true",
                        help="Skip runs that already have an entry in results.jsonl.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only execute the first N runs of the config (smoke testing).")


def _results_path(entries, output_dir) -> Path:
    if output_dir:
        return Path(output_dir) / "results.jsonl"
    return Path(entries[0]["log_file"]).parent / "results.jsonl"


def _execute(run_fn, settings, context, plain_log, echo):
    """Run one pentest inside its own log file. Never raises: errors become part of the result."""
    record = {k: v for k, v in settings.items() if k != "log_file"}
    record["log_file"] = settings["log_file"]
    started = time.time()
    with run_log(settings["log_file"], plain=plain_log, echo=echo):
        try:
            record.update(run_fn(settings, context))
            record["error"] = None
        except Exception as e:
            print(f"\n--- ERROR during agent execution ---")
            print(f"Error details: {e}")
            traceback.print_exc()
            record.update({"security": False, "utility": None, "error": f"{type(e).__name__}: {e}"})
    record["duration_s"] = round(time.time() - started, 1)
    return record


def run_all(entries, run_fn, key_fn, default_log_fn, args, context=None, plain_log=False):
    """Execute ``run_fn(settings, context) -> dict`` for every config entry.

    ``key_fn(settings)`` identifies a run (used by ``--resume``) and
    ``default_log_fn(settings)`` names its log file relative to the output dir.
    """
    if args.limit:
        entries = entries[:args.limit]
    for settings in entries:
        if args.output_dir:
            settings["log_file"] = str(Path(args.output_dir) / default_log_fn(settings))
        else:
            settings.setdefault("log_file", str(Path("runs") / default_log_fn(settings)))
    if not entries:
        print("Nothing to run.")
        return []

    results_file = _results_path(entries, args.output_dir)
    results_file.parent.mkdir(parents=True, exist_ok=True)

    if args.resume and results_file.exists():
        done = {json.dumps(json.loads(line)["key"]) for line in results_file.read_text().splitlines() if line.strip()}
        before = len(entries)
        entries = [s for s in entries if json.dumps(key_fn(s)) not in done]
        print(f"Resuming: {before - len(entries)} run(s) already in {results_file}, {len(entries)} left.")

    total = len(entries)
    print(f"Executing {total} run(s) with {args.workers} worker(s). Results -> {results_file}")
    records = []

    def finish(record, settings):
        record["key"] = key_fn(settings)
        with open(results_file, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        records.append(record)
        status = "ERROR" if record["error"] else ("SUCCESS" if record["security"] else "failure")
        print(f"[{len(records)}/{total}] {' / '.join(map(str, record['key']))}: {status} "
              f"({record['duration_s']}s, log: {record['log_file']})", flush=True)

    if args.workers <= 1:
        for settings in entries:
            finish(_execute(run_fn, settings, context, plain_log, echo=True), settings)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_execute, run_fn, s, context, plain_log, False): s for s in entries}
            for future in as_completed(futures):
                finish(future.result(), futures[future])

    successes = sum(bool(r["security"]) for r in records)
    errors = sum(bool(r["error"]) for r in records)
    if records:
        print(f"\nDone. Attack success: {successes}/{len(records)} ({100 * successes / len(records):.1f}%)"
              + (f", {errors} run(s) errored" if errors else ""))
    return records
