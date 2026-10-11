#!/usr/bin/env python3
"""
Run TopicAttack-style attacks against AgentDojo with various defenses.

This script is modular and allows testing different defenses while maintaining
consistent evaluation of ASR (Attack Success Rate) and utility metrics.

Usage:
    # Run with default defense (spotlighting_with_delimiting)
    python run_topicattack_with_defense.py \
        --payload_file data/agentdojo_banking0_attack_complete.json \
        --suite_name banking

    # Run with a different defense
    python run_topicattack_with_defense.py \
        --payload_file data/agentdojo_slack2_attack_complete.json \
        --suite_name slack \
        --defense_name repeat_user_prompt

    # Run multiple payloads with the same defense
    python run_topicattack_with_defense.py \
        --payload_patterns "data/agentdojo_*_attack_complete.json" \
        --suite_name banking \
        --defense_name spotlighting_with_delimiting

    # Verbose mode to see full conversations
    python run_topicattack_with_defense.py \
        --payload_file data/agentdojo_banking0_attack_complete.json \
        --suite_name banking \
        --verbose
"""

import argparse
import json
import os
import sys
import datetime
import requests
import glob
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class DefenseConfig:
    """Configuration for a defense mechanism."""
    name: str
    """Defense name to pass to the API."""

    def to_dict(self) -> dict:
        """Convert to dictionary for API requests."""
        return {"defense_name": self.name}


@dataclass
class EvaluationResult:
    """Result of a single attack evaluation."""
    entry_index: int
    instruction: str
    security: bool
    utility: bool
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """True if neither security nor utility failed catastrophically."""
        return self.error is None


# ── Helpers ──────────────────────────────────────────────────────────────────

class Logger:
    """Dual-output logger (console + file)."""

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        with open(self.path, "w") as f:
            f.write("")

    def log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def jload(path: str) -> list[dict]:
    """Load JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def discover_payload_files(pattern: str) -> list[str]:
    """Discover payload files matching a glob pattern."""
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files match pattern: {pattern}")
    return files


def parse_task_pair(s: str) -> tuple[str, str]:
    """Parse 'user_task_1:injection_task_3' into (user, injection) tuple."""
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(
            f"Invalid task pair '{s}'. Expected format: user_task_ID:injection_task_ID"
        )
    return parts[0].strip(), parts[1].strip()


def extract_injection_task_from_filename(filename: str) -> Optional[str]:
    """Extract injection task number from filename.
    
    Filename format: agentdojo_{suite}{injection_task_number}_attack_complete.json
    Example: agentdojo_slack1_attack_complete.json -> injection_task_1
    """
    import re
    # Match pattern like "agentdojo_slack1_attack_complete.json"
    match = re.search(r'agentdojo_\w+(\d+)_attack_complete\.json', filename)
    if match:
        task_num = match.group(1)
        return f"injection_task_{task_num}"
    return None


def extract_injection_task_number(filename: str) -> Optional[int]:
    """Extract just the injection task number from filename as integer.
    
    Example: agentdojo_slack1_attack_complete.json -> 1
    """
    match = re.search(r'agentdojo_\w+(\d+)_attack_complete\.json', filename)
    if match:
        return int(match.group(1))
    return None


def discover_suite_structure(payload_files: list[str], logger: Logger) -> dict:
    """Discover the structure of a suite by analyzing payload files.
    
    Returns:
        {
            'injection_task_numbers': [list of integers],
            'num_injection_tasks': int,
            'num_user_tasks': int,
            'files_by_injection_task': {injection_task_num: [files]},
        }
    """
    injection_task_numbers = set()
    files_by_injection_task = {}
    num_user_tasks = None
    
    # Discover injection tasks from filenames
    for payload_file in payload_files:
        inj_task_num = extract_injection_task_number(payload_file)
        if inj_task_num is not None:
            injection_task_numbers.add(inj_task_num)
            if inj_task_num not in files_by_injection_task:
                files_by_injection_task[inj_task_num] = []
            files_by_injection_task[inj_task_num].append(payload_file)
    
    # Discover user tasks by loading first file and counting entries
    if payload_files:
        try:
            first_file = payload_files[0]
            data = jload(first_file)
            num_user_tasks = len(data)
        except Exception as e:
            logger.log(f"WARNING: Could not load first file to determine user task count: {e}")
            num_user_tasks = 0
    
    injection_task_numbers = sorted(injection_task_numbers)
    
    return {
        'injection_task_numbers': injection_task_numbers,
        'num_injection_tasks': len(injection_task_numbers),
        'num_user_tasks': num_user_tasks,
        'files_by_injection_task': files_by_injection_task,
    }


def _format_message(msg: dict) -> str:
    """Format a single ChatMessage dict for verbose logging."""
    role = msg.get("role", "unknown").upper()
    lines = [f"    [{role}]"]

    content = msg.get("content")
    if content:
        if isinstance(content, str):
            lines.append(f"      {content}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    lines.append(f"      {block.get('content', '')}")
                else:
                    lines.append(f"      {block}")

    tool_calls = msg.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            if isinstance(tc, dict):
                func_field = tc.get("function", {})
                if isinstance(func_field, dict):
                    name = func_field.get("name", "?")
                    args = func_field.get("arguments", {})
                elif isinstance(func_field, str):
                    name = func_field
                    args = tc.get("args", {})
                else:
                    name = "?"
                    args = {}
                lines.append(
                    f"      -> tool_call: {name}("
                    f"{json.dumps(args, default=str, ensure_ascii=False)[:300]})"
                )

    if msg.get("tool_call_id"):
        lines.append(f"      (tool_call_id: {msg['tool_call_id']})")

    return "\n".join(lines)


def _log_full_conversation(logger: Logger, messages: list[dict], extra: dict | None = None):
    """Log every message in the conversation."""
    logger.log("  ── Full conversation ──")
    if extra:
        if "injection_candidates" in extra:
            logger.log(f"  Injection candidates: {extra['injection_candidates']}")
        if "user_task_prompt" in extra:
            logger.log(f"  User task prompt    : {extra['user_task_prompt']}")
    for i, msg in enumerate(messages):
        logger.log(f"  msg[{i}] {_format_message(msg)}")
    logger.log("  ── End of conversation ──")


# ── REST API Helpers ─────────────────────────────────────────────────────────

def _check_response(resp: requests.Response) -> dict:
    """Check HTTP response; raise on error."""
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:2000]}
        error_msg = body.get("error", resp.text[:500])
        tb = body.get("traceback", "")
        raise RuntimeError(
            f"HTTP {resp.status_code} from {resp.url}\n"
            f"  error: {error_msg}\n"
            f"  traceback: {tb}"
        )
    return resp.json()


def api_create_session(
    base_url: str,
    suite_name: str,
    user_task_id: str,
    model_name: str,
    injection_task_name: str,
    defense_config: Optional[DefenseConfig] = None,
) -> str:
    """Create a session and return its session_id."""
    payload = {
        "suite_name": suite_name,
        "user_task_id": user_task_id,
        "model_name": model_name,
        "injection_task_name": injection_task_name,
    }
    if defense_config:
        payload["defense_name"] = defense_config.name

    resp = requests.post(f"{base_url}/sessions", json=payload, timeout=60)
    return _check_response(resp)["session_id"]


def api_inject_via_environment(base_url: str, session_id: str, content: str) -> dict:
    """Inject content into the environment and return the full response dict."""
    resp = requests.post(
        f"{base_url}/sessions/{session_id}/inject_via_environment",
        json={"content": content},
        timeout=120,
    )
    return _check_response(resp)


def api_delete_session(base_url: str, session_id: str):
    """Delete a session."""
    resp = requests.delete(f"{base_url}/sessions/{session_id}", timeout=30)
    _check_response(resp)


def api_health(base_url: str) -> dict:
    """Check API health."""
    resp = requests.get(f"{base_url}/health", timeout=10)
    resp.raise_for_status()
    return resp.json()


# ── Evaluation Engine ────────────────────────────────────────────────────────

class DefenseEvaluator:
    """Evaluates attacks against defenses."""

    def __init__(
        self,
        api_url: str,
        suite_name: str,
        model_name: str,
        defense_config: DefenseConfig,
        logger: Logger,
        verbose: bool = False,
    ):
        self.api_url = api_url
        self.suite_name = suite_name
        self.model_name = model_name
        self.defense_config = defense_config
        self.logger = logger
        self.verbose = verbose

    def evaluate_entry(
        self,
        idx: int,
        entry: dict,
        user_task: str,
        inj_task: str,
    ) -> EvaluationResult:
        """Evaluate a single attack entry."""
        logger = self.logger
        result = EvaluationResult(
            entry_index=idx,
            instruction=entry.get("instruction", "")[:80],
            security=False,
            utility=False,
        )

        session_id = None
        try:
            # Create session
            session_id = api_create_session(
                base_url=self.api_url,
                suite_name=self.suite_name,
                user_task_id=user_task,
                model_name=self.model_name,
                injection_task_name=inj_task,
                defense_config=self.defense_config,
            )
            logger.log(f"  session_id  : {session_id}")

            # Inject via environment
            injection_content = entry.get("injection", "")
            api_result = api_inject_via_environment(
                self.api_url, session_id, injection_content
            )

            result.security = bool(api_result.get("security", False))
            result.utility = bool(api_result.get("utility", False))

            logger.log(f"  security (attack succeeded): {result.security}")
            logger.log(f"  utility  (task completed) : {result.utility}")

            messages = api_result.get("messages", [])

            # Verbose: log the full conversation
            if self.verbose:
                _log_full_conversation(
                    logger,
                    messages,
                    extra={
                        k: api_result[k]
                        for k in ("injection_candidates", "user_task_prompt")
                        if k in api_result
                    },
                )
            else:
                # Default: log a snippet of the last assistant message
                for msg in reversed(messages):
                    if msg.get("role") == "assistant":
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            text = " ".join(
                                b.get("content", "") if isinstance(b, dict) else str(b)
                                for b in content
                            )
                        else:
                            text = str(content)
                        logger.log(f"  assistant response (first 200 chars): {text[:200]}")
                        break

        except Exception as exc:
            result.error = str(exc)
            logger.log(f"  ERROR: {exc}")

        finally:
            # Delete session
            if session_id:
                try:
                    api_delete_session(self.api_url, session_id)
                    logger.log(f"  session deleted")
                except Exception as del_exc:
                    logger.log(f"  WARNING: failed to delete session: {del_exc}")

        return result


# ── Main ─────────────────────────────────────────────────────────────────────

def run(args):
    # Setup
    defense_config = DefenseConfig(name=args.defense_name)
    log_file = (
        args.log_file
        or f"logs/defense_{args.defense_name}_{datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.txt"
    )
    logger = Logger(log_file)

    logger.log(f"Arguments: {vars(args)}")
    logger.log(f"Defense: {defense_config.name}")

    # Verify the server is reachable
    try:
        health = api_health(args.api_url)
        logger.log(f"Server OK – active sessions: {health['active_sessions']}")
    except Exception as exc:
        logger.log(f"ERROR: Cannot reach REST API at {args.api_url}: {exc}")
        sys.exit(1)

    # Discover payload files
    payload_files = []
    if args.payload_file:
        if not os.path.exists(args.payload_file):
            logger.log(f"ERROR: Payload file not found: {args.payload_file}")
            sys.exit(1)
        payload_files = [args.payload_file]
    elif args.payload_patterns:
        try:
            payload_files = discover_payload_files(args.payload_patterns)
        except FileNotFoundError as e:
            logger.log(f"ERROR: {e}")
            sys.exit(1)
    else:
        logger.log("ERROR: Must provide either --payload_file or --payload_patterns")
        sys.exit(1)

    logger.log(f"Found {len(payload_files)} payload file(s)")

    # Discover suite structure
    suite_structure = discover_suite_structure(payload_files, logger)
    logger.log(f"\n{'='*70}")
    logger.log(f"SUITE STRUCTURE ANALYSIS")
    logger.log(f"{'='*70}")
    logger.log(f"  Suite name                : {args.suite_name}")
    logger.log(f"  Injection tasks found     : {suite_structure['injection_task_numbers']}")
    logger.log(f"  Total injection tasks     : {suite_structure['num_injection_tasks']}")
    logger.log(f"  User tasks per file       : {suite_structure['num_user_tasks']}")
    logger.log(f"  Total combinations        : {suite_structure['num_injection_tasks']} × {suite_structure['num_user_tasks']} = {suite_structure['num_injection_tasks'] * suite_structure['num_user_tasks']}")
    logger.log(f"{'='*70}\n")

    # Create evaluator
    evaluator = DefenseEvaluator(
        api_url=args.api_url,
        suite_name=args.suite_name,
        model_name=args.model_name,
        defense_config=defense_config,
        logger=logger,
        verbose=args.verbose,
    )

    # Resolve task pairs
    task_pairs = []
    if args.tasks:
        parsed = [parse_task_pair(t) for t in args.tasks]
        if len(parsed) == 1:
            task_pairs = parsed
        else:
            logger.log(
                f"WARNING: --tasks provided with {len(parsed)} pairs. "
                f"Will reuse the first pair for all entries."
            )
            task_pairs = [parsed[0]]

    logger.log(f"Task pair mode: {'explicit' if task_pairs else 'auto-detected from filenames'}")

    logger.log(f"Using task pair(s): {task_pairs if task_pairs else 'will be auto-detected'}")

    # Run attacks on all payload files
    all_results: list[EvaluationResult] = []

    for payload_idx, payload_file in enumerate(payload_files):
        logger.log(f"\n{'='*70}")
        logger.log(f"Payload file {payload_idx+1}/{len(payload_files)}: {payload_file}")
        logger.log(f"{'='*70}")

        try:
            data = jload(payload_file)
        except Exception as e:
            logger.log(f"ERROR: Failed to load {payload_file}: {e}")
            continue

        logger.log(f"Loaded {len(data)} attack entries")

        # Auto-detect injection task from filename if not explicitly provided
        injection_task = None
        if not task_pairs:
            injection_task = extract_injection_task_from_filename(payload_file)
            if injection_task:
                logger.log(f"Auto-detected {injection_task} from filename")
            else:
                logger.log(f"WARNING: Could not extract injection task from filename, using default")
                injection_task = "injection_task_0"

        for idx, entry in enumerate(data):
            logger.log(f"\n{'-'*70}")
            logger.log(f"Entry {idx+1}/{len(data)}")
            logger.log(f"  instruction : {entry.get('instruction', '')[:80]}...")
            logger.log(f"  injection_output keyword: {entry.get('injection_output', '?')}")

            # Determine task pair for this entry
            if task_pairs:
                # Use explicitly provided task pair
                user_task, inj_task = task_pairs[0]
            else:
                # Entry index corresponds to user_task number
                # Injection task comes from filename
                user_task = f"user_task_{idx}"
                inj_task = injection_task

            logger.log(f"  task pair   : {user_task}:{inj_task}")

            result = evaluator.evaluate_entry(idx, entry, user_task, inj_task)
            all_results.append(result)

    # Summary
    n = len(all_results)
    successful = sum(1 for r in all_results if r.success)
    asr = sum(1 for r in all_results if r.security) / n * 100 if n else 0
    acc = sum(1 for r in all_results if r.utility) / n * 100 if n else 0
    errors = n - successful

    logger.log(f"\n{'#'*70}")
    logger.log(f"DEFENSE EVALUATION SUMMARY: {defense_config.name}")
    logger.log(f"{'#'*70}")
    logger.log(f"  Total entries       : {n}")
    logger.log(f"  Successful runs     : {successful}/{n}")
    logger.log(f"  Errors              : {errors}")
    logger.log(f"  ASR  (attack)       : {asr:.2f}%  ({sum(1 for r in all_results if r.security)}/{n})")
    logger.log(f"  Utility (task)      : {acc:.2f}%  ({sum(1 for r in all_results if r.utility)}/{n})")
    logger.log(f"{'#'*70}")
    logger.log(f"Log file: {log_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run TopicAttack attacks against AgentDojo with various defenses",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Payload options
    payload_group = parser.add_mutually_exclusive_group(required=True)
    payload_group.add_argument(
        "--payload_file",
        type=str,
        help="Path to a single attack-complete JSON file",
    )
    payload_group.add_argument(
        "--payload_patterns",
        type=str,
        help="Glob pattern to match multiple payload files (e.g., 'data/agentdojo_*_attack_complete.json')",
    )

    # Defense and evaluation options
    parser.add_argument(
        "--defense_name",
        type=str,
        default="spotlighting_with_delimiting",
        help="Defense name to test (default: spotlighting_with_delimiting)",
    )
    parser.add_argument(
        "--suite_name",
        type=str,
        default="banking",
        help="AgentDojo suite name (default: banking)",
    )
    parser.add_argument(
        "--model_name",
        type=str,
        default="gpt-4.1-2025-04-14",
        help="Victim model name (default: gpt-4.1-2025-04-14)",
    )
    parser.add_argument(
        "--tasks",
        type=str,
        nargs="+",
        default=None,
        help=(
            "Space-separated user_task:injection_task pairs. "
            "Example: user_task_1:injection_task_1"
        ),
    )

    # API and logging options
    parser.add_argument(
        "--api_url",
        type=str,
        default="http://127.0.0.1:5000",
        help="Base URL of the REST API server (default: http://127.0.0.1:5000)",
    )
    parser.add_argument(
        "--log_file",
        type=str,
        default=None,
        help="Path to output log file (default: auto-generated with timestamp)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Log the full agent conversation for every attack entry",
    )

    args = parser.parse_args()
    run(args)
