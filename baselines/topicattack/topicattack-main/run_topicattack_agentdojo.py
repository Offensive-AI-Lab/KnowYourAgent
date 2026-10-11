#!/usr/bin/env python3
"""
Run TopicAttack-style attacks against AgentDojo via the REST API.

For each entry in the attack data file, this script:
  1. Creates a new AgentDojoChatSession via the REST API
  2. Injects the attack payload into the environment
  3. Records security (attack success) and utility results
  4. Deletes the session

Usage:
    # First, start the REST API server:
    python Benchmarks/agentdojo_edited/src/rest_api.py --port 5000

    # Then run this script:
    python run_topicattack_agentdojo.py \
        --data_path ./data/agentdojo_slack_attack_complete.json \
        --tasks user_task_1:injection_task_1 user_task_6:injection_task_3 \
        --suite_name slack \
        --model_name gpt-4o-2024-05-13 \
        --api_url http://127.0.0.1:5000 \
        --log_file logs/topicattack_agentdojo_results.txt

    If --tasks is omitted, a single default pair (user_task_0:injection_task_0)
    is used for every entry.  You can supply one pair per attack entry or a
    single pair that is reused for all entries.
"""

import argparse
import json
import os
import sys
import datetime
import requests


# ── Helpers ──────────────────────────────────────────────────────────────────

def jload(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class Logger:
    """Simple dual-output logger (console + file)."""

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        # Truncate the log at start
        with open(self.path, "w") as f:
            f.write("")

    def log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def parse_task_pair(s: str) -> tuple[str, str]:
    """Parse 'user_task_1:injection_task_3' into a (user, injection) tuple."""
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(
            f"Invalid task pair '{s}'. Expected format: user_task_ID:injection_task_ID"
        )
    return parts[0].strip(), parts[1].strip()


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
                # Support both OpenAI format {"function": {"name":…, "arguments":…}}
                # and agentdojo format {"function": "name", "args": {…}}
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
    """Log every message in the conversation when verbose mode is on."""
    logger.log("  ── Full conversation ──")
    if extra:
        if "injection_candidates" in extra:
            logger.log(f"  Injection candidates: {extra['injection_candidates']}")
        if "user_task_prompt" in extra:
            logger.log(f"  User task prompt    : {extra['user_task_prompt']}")
    for i, msg in enumerate(messages):
        logger.log(f"  msg[{i}] {_format_message(msg)}")
    logger.log("  ── End of conversation ──")


# ── REST API helpers ─────────────────────────────────────────────────────────

def _check_response(resp: requests.Response) -> dict:
    """Check HTTP response; on error, raise with the server's error body included."""
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
    defense_name: str | None = None,
) -> str:
    """Create a session and return its session_id."""
    payload = {
        "suite_name": suite_name,
        "user_task_id": user_task_id,
        "model_name": model_name,
        "injection_task_name": injection_task_name,
    }
    if defense_name:
        payload["defense_name"] = defense_name

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
    resp = requests.get(f"{base_url}/health", timeout=10)
    resp.raise_for_status()
    return resp.json()


# ── Main ─────────────────────────────────────────────────────────────────────

def run(args):
    logger = Logger(args.log_file)
    logger.log(f"Arguments: {vars(args)}")

    # Verify the server is reachable
    try:
        health = api_health(args.api_url)
        logger.log(f"Server OK – active sessions: {health['active_sessions']}")
    except Exception as exc:
        logger.log(f"ERROR: Cannot reach REST API at {args.api_url}: {exc}")
        sys.exit(1)

    # Load attack data
    data = jload(args.data_path)
    logger.log(f"Loaded {len(data)} attack entries from {args.data_path}")

    # Resolve task pairs
    task_pairs = []
    if args.tasks:
        parsed = [parse_task_pair(t) for t in args.tasks]
        if len(parsed) == 1:
            # Reuse the single pair for every entry
            task_pairs = parsed * len(data)
        elif len(parsed) == len(data):
            task_pairs = parsed
        else:
            logger.log(
                f"ERROR: --tasks must provide either 1 pair (reused) "
                f"or exactly {len(data)} pairs (one per entry). Got {len(parsed)}."
            )
            sys.exit(1)
    else:
        task_pairs = [("user_task_0", "injection_task_0")] * len(data)

    # Run each attack
    security_results: list[bool] = []
    utility_results: list[bool] = []

    for idx, (entry, (user_task, inj_task)) in enumerate(zip(data, task_pairs)):
        logger.log(f"\n{'='*60}")
        logger.log(
            f"Entry {idx+1}/{len(data)} | "
            f"user_task={user_task} | injection_task={inj_task}"
        )
        logger.log(f"  instruction : {entry.get('instruction', '')[:80]}...")
        logger.log(f"  injection_output keyword: {entry.get('injection_output', '?')}")

        session_id = None
        try:
            # 1) Create session
            session_id = api_create_session(
                base_url=args.api_url,
                suite_name=args.suite_name,
                user_task_id=user_task,
                model_name=args.model_name,
                injection_task_name=inj_task,
                defense_name=args.defense_name,
            )
            logger.log(f"  session_id  : {session_id}")

            # 2) Inject via environment
            injection_content = entry.get("injection", "")
            result = api_inject_via_environment(
                args.api_url, session_id, injection_content
            )

            security = result.get("security", False)
            utility = result.get("utility", False)
            security_results.append(bool(security))
            utility_results.append(bool(utility))

            logger.log(f"  security (attack succeeded): {security}")
            logger.log(f"  utility  (task completed) : {utility}")

            messages = result.get("messages", [])

            # Verbose: log the full conversation
            if args.verbose:
                _log_full_conversation(
                    logger,
                    messages,
                    extra={
                        k: result[k]
                        for k in ("injection_candidates", "user_task_prompt")
                        if k in result
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
            logger.log(f"  ERROR: {exc}")
            security_results.append(False)
            utility_results.append(False)

        finally:
            # 3) Delete session
            if session_id:
                try:
                    api_delete_session(args.api_url, session_id)
                    logger.log(f"  session deleted")
                except Exception as del_exc:
                    logger.log(f"  WARNING: failed to delete session: {del_exc}")

    # Summary
    n = len(data)
    asr = sum(security_results) / n * 100 if n else 0
    acc = sum(utility_results) / n * 100 if n else 0

    logger.log(f"\n{'#'*60}")
    logger.log(f"  Total entries     : {n}")
    logger.log(f"  ASR  (attack)     : {asr:.2f}%  ({sum(security_results)}/{n})")
    logger.log(f"  Accuracy (utility): {acc:.2f}%  ({sum(utility_results)}/{n})")
    logger.log(f"{'#'*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run TopicAttack prompts against AgentDojo via REST API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--data_path",
        type=str,
        required=True,
        help="Path to the attack-complete JSON file (output of construct_attack.py)",
    )
    parser.add_argument(
        "--tasks",
        type=str,
        nargs="+",
        default=None,
        help=(
            "Space-separated list of user_task:injection_task pairs. "
            "Provide one pair (reused for all entries) or one per entry. "
            "Example: user_task_1:injection_task_1 user_task_6:injection_task_3"
        ),
    )
    parser.add_argument(
        "--suite_name",
        type=str,
        default="slack",
        help="AgentDojo suite name (default: slack)",
    )
    parser.add_argument(
        "--model_name",
        type=str,
        default="gpt-4o-2024-05-13",
        help="Victim model name (default: gpt-4o-2024-05-13)",
    )
    parser.add_argument(
        "--defense_name",
        type=str,
        default=None,
        help="Optional defense name (e.g. repeat_user_prompt)",
    )
    parser.add_argument(
        "--api_url",
        type=str,
        default="http://127.0.0.1:5000",
        help="Base URL of the REST API server (default: http://127.0.0.1:5000)",
    )
    parser.add_argument(
        "--log_file",
        type=str,
        default="logs/topicattack_agentdojo_results.txt",
        help="Path to the output log file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Log the full agent conversation for every attack entry",
    )

    args = parser.parse_args()
    run(args)
