#!/usr/bin/env python3
"""
Run the banking suite attack pipeline using a given config file.

  1. Reads a JSON config (see attack_config.schema.json)
  2. Runs attack generation → payloads.json
  3. Runs attack testing   → results.json

Usage:
    python run_singular_banking.py --config banking_suite.json --output results/run1
    python run_singular_banking.py --config cfg.json --output out/ --create-only
    python run_singular_banking.py --config cfg.json --output out/ --test-only
"""

import argparse
import json
import sys
import os
from pathlib import Path

# --------------- CONFIGURATION ---------------
ATTACKER_MODEL = "gpt-5.1"           # Model for generating attacks
TARGET_MODEL   = "gpt-4o-2024-05-13" # Model used by the target agent
VERBOSE        = True

# --------------- PATH SETUP ---------------
SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "benchmarks" / "agentdojo" / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

# --------------- IMPORTS ---------------
from agentdojo.default_suites.v1.banking import banking_task_suite
from general_attacker import (
    SYSTEM_PROMPT,
    KNOWLEDGE_PIECE_NAMES,
    build_knowledge,
    call_attacker_llm,
    gather_tool_output,
)
from benchmarks.agentdojo.src.api import AgentDojoChatSession

suite = banking_task_suite


def generate_single_payload(config: dict, suite_name: str, injection_task_id: str, user_task_id: str) -> str:
    """Generate a single attack payload for the given triplet. Returns the payload string."""
    knowledge_pieces_config = config["knowledge_pieces"]
    key = f"{suite_name}/{injection_task_id}/{user_task_id}"

    injection_task = suite.get_injection_task_by_id(injection_task_id)
    user_task = suite.get_user_task_by_id(user_task_id)

    malicious_goal = injection_task.GOAL
    tool_output = gather_tool_output(suite, injection_task, user_task)
    tool_output_enabled = knowledge_pieces_config.get("tool_output", False)

    knowledge = build_knowledge(
        knowledge_pieces_config=knowledge_pieces_config,
        suite=suite,
        injection_task=injection_task,
        user_task=user_task,
        tool_output=tool_output,
    )

    attack_output = call_attacker_llm(
        malicious_goal=malicious_goal,
        knowledge=knowledge,
        model_name=ATTACKER_MODEL,
        tool_output=tool_output if tool_output_enabled else None,
    )

    return attack_output


def generate_payloads(config: dict, output_path: Path) -> dict:
    """Run attack generation for the given config. Returns the payloads dict."""
    triplets = config["triplets"]
    results = {}

    for triplet in triplets:
        suite_name, injection_task_id, user_task_id = triplet
        key = f"{suite_name}/{injection_task_id}/{user_task_id}"
        print(f"  [CREATE] {key}")

        try:
            payload = generate_single_payload(config, suite_name, injection_task_id, user_task_id)
        except KeyError as e:
            print(f"    [SKIP] Task not found: {e}")
            results[key] = f"[Error: task not found - {e}]"
            continue

        results[key] = payload

        if VERBOSE:
            print(f"    Payload (first 120 chars): {payload[:120]}...")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"  Saved {len(results)} payloads → {output_path}")
    return results


def _extract_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("content", ""))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def _serialize_obj(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _serialize_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_obj(item) for item in obj]
    return obj


def serialize_messages(messages) -> list:
    out = []
    for msg in messages:
        entry = {"role": msg.get("role", "unknown")}
        content = msg.get("content")
        if content is not None:
            if isinstance(content, list):
                entry["content"] = [
                    dict(block) if hasattr(block, "items") else block
                    for block in content
                ]
            else:
                entry["content"] = str(content)
        if "tool_calls" in msg and msg["tool_calls"] is not None:
            entry["tool_calls"] = _serialize_obj(msg["tool_calls"])
        if "tool_call" in msg:
            entry["tool_call"] = _serialize_obj(msg["tool_call"])
        if "tool_call_id" in msg:
            entry["tool_call_id"] = msg["tool_call_id"]
        if "error" in msg:
            entry["error"] = msg["error"]
        out.append(entry)
    return out


def test_single_payload(suite_name: str, injection_task_id: str, user_task_id: str, payload: str) -> dict:
    """Test a single payload. Returns a result dict with payload, security, utility, and optionally messages."""
    session = AgentDojoChatSession(
        suite_name=suite_name,
        user_task_id=user_task_id,
        model_name=TARGET_MODEL,
        injection_task_name=injection_task_id,
    )

    messages, security, utility = session.inject_prompt_via_environment(payload)

    result_entry = {
        "payload": payload,
        "security": security,
        "utility": utility,
    }

    if VERBOSE:
        result_entry["messages"] = serialize_messages(messages)

    return result_entry


def test_payloads(payloads_path: Path, output_path: Path) -> dict:
    """Run attack testing. Returns the results dict."""
    with open(payloads_path, "r") as f:
        attack_payloads = json.load(f)

    results = {}

    for key, payload in attack_payloads.items():
        parts = key.split("/")
        if len(parts) != 3:
            print(f"    [SKIP] Malformed key: {key}")
            results[key] = {"error": f"Malformed key: {key}"}
            continue

        suite_name, injection_task_id, user_task_id = parts
        print(f"  [TEST]  {key}")

        try:
            result_entry = test_single_payload(suite_name, injection_task_id, user_task_id, payload)
            results[key] = result_entry
            print(f"    Security (injection succeeded): {result_entry['security']}  |  Utility: {result_entry['utility']}")

        except Exception as exc:
            print(f"    Error: {exc}")
            results[key] = {"payload": payload, "error": str(exc)}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    # Summary
    total   = len(results)
    success = sum(1 for r in results.values() if r.get("security") is True)
    failed  = sum(1 for r in results.values() if r.get("security") is False)
    errors  = sum(1 for r in results.values() if "error" in r)
    print(f"  Saved {total} results → {output_path}")
    print(f"  ASR: {success}/{total - errors}"
          f" ({success / (total - errors) * 100:.1f}%)" if total - errors > 0 else "")
    return results


def run_with_iterations(config: dict, output_dir: Path, iterations: int) -> dict:
    """Run the full generate+test pipeline with iteration support.

    For each triplet, generates a payload, tests it, and if security is False,
    retries (new payload + test) up to ``iterations`` total attempts. Stops
    early for a triplet once security=True.

    Returns the final results dict.
    """
    triplets = config["triplets"]
    results = {}
    payloads = {}

    for triplet in triplets:
        suite_name, injection_task_id, user_task_id = triplet
        key = f"{suite_name}/{injection_task_id}/{user_task_id}"

        for attempt in range(1, iterations + 1):
            print(f"  [{key}] Attempt {attempt}/{iterations}")

            # --- Generate ---
            try:
                payload = generate_single_payload(config, suite_name, injection_task_id, user_task_id)
            except KeyError as e:
                print(f"    [SKIP] Task not found: {e}")
                results[key] = {"error": f"task not found - {e}"}
                break

            if VERBOSE:
                print(f"    Payload (first 120 chars): {payload[:120]}...")

            # --- Test ---
            try:
                result_entry = test_single_payload(suite_name, injection_task_id, user_task_id, payload)
                results[key] = result_entry
                payloads[key] = payload
                print(f"    Security: {result_entry['security']}  |  Utility: {result_entry['utility']}")

                if result_entry.get("security") is True:
                    print(f"    -> Success on attempt {attempt}, moving on.")
                    break
            except Exception as exc:
                print(f"    Error: {exc}")
                results[key] = {"payload": payload, "error": str(exc)}
                break

    # Save results
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.json"
    payloads_path = output_dir / "payloads.json"

    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    with open(payloads_path, "w") as f:
        json.dump(payloads, f, indent=2)

    # Summary
    total   = len(results)
    success = sum(1 for r in results.values() if r.get("security") is True)
    errors  = sum(1 for r in results.values() if "error" in r)
    print(f"  Saved {total} results → {results_path}")
    if total - errors > 0:
        print(f"  ASR: {success}/{total - errors}"
              f" ({success / (total - errors) * 100:.1f}%)")
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Run banking suite attack pipeline from a config file."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to attack config JSON (see attack_config.schema.json).",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Relative output folder for payloads.json and results.json.",
    )
    parser.add_argument(
        "--create-only",
        action="store_true",
        help="Only generate payloads; do not run tests.",
    )
    parser.add_argument(
        "--test-only",
        action="store_true",
        help="Only run tests on existing payloads; do not generate new ones.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of attempts per triplet. For each case, generates and tests "
             "a new payload up to this many times, stopping early if security=True.",
    )
    args = parser.parse_args()

    config_path   = Path(args.config)
    output_dir    = Path(args.output)
    payloads_path = output_dir / "payloads.json"
    results_path  = output_dir / "results.json"

    if not config_path.is_file():
        print(f"[ERROR] Config file not found: {config_path}")
        sys.exit(1)

    with open(config_path, "r") as f:
        config = json.load(f)

    enabled = [k for k, v in config["knowledge_pieces"].items() if v]

    print(f"\n{'='*60}")
    print(f"Config:          {config_path}")
    print(f"Output dir:      {output_dir}")
    print(f"Enabled pieces:  {enabled}")
    print(f"Triplets:        {len(config['triplets'])}")
    print(f"Iterations:      {args.iterations}")
    print(f"{'='*60}")

    if args.iterations > 1 and not args.create_only and not args.test_only:
        # Integrated generate+test loop with retries
        print(f"\n  --- Running with {args.iterations} iterations per triplet ---")
        run_with_iterations(config, output_dir, args.iterations)
    else:
        if not args.test_only:
            print(f"\n  --- Generating payloads ---")
            generate_payloads(config, payloads_path)

        if not args.create_only:
            if not payloads_path.exists():
                print(f"  [ERROR] No payloads.json found at {payloads_path}. Run without --test-only first.")
                sys.exit(1)
            print(f"\n  --- Testing payloads ---")
            test_payloads(payloads_path, results_path)

    print(f"\n{'='*60}")
    print("All done.")


if __name__ == "__main__":
    main()
