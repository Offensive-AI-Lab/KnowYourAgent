#!/usr/bin/env python3
"""
REST API server that wraps AgentDojoChatSession and utility functions
from api.py, exposing them over HTTP on localhost.

Sessions are stored in-memory and are cleared on server restart.
"""

import uuid
import traceback
import sys
from pathlib import Path
from flask import Flask, request, jsonify

# Add parent directories to path to enable imports
_script_dir = Path(__file__).resolve().parent
_root_dir = _script_dir.parent.parent.parent
if str(_root_dir) not in sys.path:
    sys.path.insert(0, str(_root_dir))

from benchmarks.agentdojo.src.api import (
    AgentDojoChatSession,
    get_injection_goal,
    get_user_task_prompt,
)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory session store – cleared every time the process restarts
# ---------------------------------------------------------------------------
_sessions: dict[str, AgentDojoChatSession] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_tool_call(tc):
    """Convert a tool call (which may contain FunctionCall/BaseModel objects) to
    a JSON-safe structure."""
    if isinstance(tc, dict):
        return {k: _serialize_tool_call(v) for k, v in tc.items()}
    if isinstance(tc, list):
        return [_serialize_tool_call(item) for item in tc]
    # Pydantic BaseModel (e.g. FunctionCall)
    if hasattr(tc, "model_dump"):
        return tc.model_dump()
    if hasattr(tc, "__dict__"):
        return {k: _serialize_tool_call(v) for k, v in vars(tc).items()}
    return tc


def _serialize_messages(messages) -> list[dict]:
    """Best-effort JSON-safe conversion of ChatMessage sequences."""
    out = []
    for msg in messages:
        entry: dict = {"role": msg.get("role", "unknown")}
        content = msg.get("content")
        if content is not None:
            if isinstance(content, str):
                entry["content"] = content
            elif isinstance(content, list):
                entry["content"] = [
                    dict(block) if hasattr(block, "items") else block
                    for block in content
                ]
            else:
                entry["content"] = str(content)
        # Forward optional fields, serializing complex objects
        if "tool_call_id" in msg:
            entry["tool_call_id"] = msg["tool_call_id"]
        if "tool_calls" in msg:
            entry["tool_calls"] = _serialize_tool_call(msg["tool_calls"])
        if "error" in msg:
            entry["error"] = msg["error"]
        out.append(entry)
    return out


def _get_session(session_id: str) -> AgentDojoChatSession:
    """Retrieve a session or raise KeyError."""
    try:
        return _sessions[session_id]
    except KeyError:
        raise KeyError(f"Session '{session_id}' not found")


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

@app.route("/sessions", methods=["POST"])
def create_session():
    """Create a new AgentDojoChatSession and return its session_id.

    JSON body (required fields marked *):
        suite_name*          str   – e.g. "slack"
        user_task_id*        str   – e.g. "user_task_1"
        model_name*          str   – e.g. "gpt-4o-2024-05-13"
        injection_task_name  str   – default "injection_task_0"
        run_dir              str   – default "runs"
        defense_name         str|null
        system_message_name  str|null
    """
    data = request.get_json(force=True)
    required = ("suite_name", "user_task_id", "model_name")
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    kwargs: dict = {
        "suite_name": data["suite_name"],
        "user_task_id": data["user_task_id"],
        "model_name": data["model_name"],
    }
    for opt in ("injection_task_name", "run_dir", "defense_name", "system_message_name"):
        if opt in data:
            kwargs[opt] = data[opt]

    try:
        session = AgentDojoChatSession(**kwargs)
    except Exception as exc:
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500

    session_id = uuid.uuid4().hex
    _sessions[session_id] = session
    return jsonify({"session_id": session_id}), 201


@app.route("/sessions", methods=["GET"])
def list_sessions():
    """List all active session IDs."""
    return jsonify({"sessions": list(_sessions.keys())}), 200


@app.route("/sessions/<session_id>", methods=["DELETE"])
def delete_session(session_id: str):
    """Delete a session by its ID."""
    if session_id not in _sessions:
        return jsonify({"error": f"Session '{session_id}' not found"}), 404
    del _sessions[session_id]
    return jsonify({"deleted": session_id}), 200


@app.route("/sessions", methods=["DELETE"])
def delete_all_sessions():
    """Delete all sessions."""
    count = len(_sessions)
    _sessions.clear()
    return jsonify({"deleted_count": count}), 200


# ---------------------------------------------------------------------------
# Session methods
# ---------------------------------------------------------------------------

@app.route("/sessions/<session_id>/init_chat", methods=["POST"])
def init_chat(session_id: str):
    """Initialise the chat for a session (runs the user-task prompt).

    No request body required.
    """
    try:
        session = _get_session(session_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404

    try:
        messages = session.init_chat()
        return jsonify({"messages": _serialize_messages(messages)}), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500


@app.route("/sessions/<session_id>/send", methods=["POST"])
def send_message(session_id: str):
    """Send a message to the agent.

    JSON body:
        message  str|null  – If null/missing the user-task prompt is used.
    """
    try:
        session = _get_session(session_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404

    data = request.get_json(force=True) if request.data else {}
    message = data.get("message")

    try:
        messages, utility, security = session.send(message)
        return jsonify({
            "messages": _serialize_messages(messages),
            "utility": utility,
            "security": security,
        }), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500


@app.route("/sessions/<session_id>/prompt_agent", methods=["POST"])
def prompt_agent(session_id: str):
    """Prompt the agent with custom content (replaces history[1]).

    JSON body:
        content*  str
    """
    try:
        session = _get_session(session_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404

    data = request.get_json(force=True)
    content = data.get("content")
    if content is None:
        return jsonify({"error": "Missing required field: content"}), 400

    try:
        history = session.prompt_agent(content)
        return jsonify({"history": _serialize_messages(history)}), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500


@app.route("/sessions/<session_id>/inject_via_environment", methods=["POST"])
def inject_via_environment(session_id: str):
    """Inject a prompt into the environment at all injection candidates.

    JSON body:
        content*  str
    """
    try:
        session = _get_session(session_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404

    data = request.get_json(force=True)
    content = data.get("content")
    if content is None:
        return jsonify({"error": "Missing required field: content"}), 400

    try:
        messages, security, utility = session.inject_prompt_via_environment(content)
        resp_body = {
            "messages": _serialize_messages(messages),
            "security": security,
            "utility": utility,
        }
        # Include extra metadata useful for verbose logging
        try:
            resp_body["injection_candidates"] = session._get_injection_candidates()
        except Exception:
            pass
        try:
            resp_body["user_task_prompt"] = session.user_task.PROMPT
        except Exception:
            pass
        return jsonify(resp_body), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500


@app.route("/sessions/<session_id>/inject_at_index", methods=["POST"])
def inject_at_index(session_id: str):
    """Inject content at a specific history index.

    JSON body:
        content*  str
        index*    int
    """
    try:
        session = _get_session(session_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404

    data = request.get_json(force=True)
    content = data.get("content")
    index = data.get("index")
    if content is None or index is None:
        return jsonify({"error": "Missing required fields: content, index"}), 400

    try:
        result = session.inject_content_at_index_limited(content, int(index))
        # The method returns (messages, success_str, utility_str)
        if isinstance(result, tuple) and len(result) == 3:
            messages, success, utility = result
            # messages could be a plain error string
            if isinstance(messages, str):
                return jsonify({"error": messages}), 400
            return jsonify({
                "messages": _serialize_messages(messages),
                "security": success,
                "utility": utility,
            }), 200
        return jsonify({"result": str(result)}), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500


@app.route("/sessions/<session_id>/history", methods=["GET"])
def get_history(session_id: str):
    """Return the full conversation history for a session."""
    try:
        session = _get_session(session_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404

    return jsonify({"history": _serialize_messages(session.get_history())}), 200


@app.route("/sessions/<session_id>/injection_candidates", methods=["GET"])
def get_injection_candidates(session_id: str):
    """Return the list of injection candidates for the session's user task."""
    try:
        session = _get_session(session_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404

    try:
        candidates = session._get_injection_candidates()
        return jsonify({"injection_candidates": candidates}), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500


# ---------------------------------------------------------------------------
# Utility endpoints (stateless – no session required)
# ---------------------------------------------------------------------------

@app.route("/utils/injection_goal", methods=["GET"])
def util_injection_goal():
    """Get the GOAL string of an injection task.

    Query params:
        suite*          str – e.g. "slack"
        injection_id*   str – e.g. "injection_task_0"
    """
    suite = request.args.get("suite")
    injection_id = request.args.get("injection_id")
    if not suite or not injection_id:
        return jsonify({"error": "Missing query params: suite, injection_id"}), 400

    try:
        goal = get_injection_goal(suite, injection_id)
        return jsonify({"suite": suite, "injection_id": injection_id, "goal": goal}), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500


@app.route("/utils/user_task_prompt", methods=["GET"])
def util_user_task_prompt():
    """Get the PROMPT string of a user task.

    Query params:
        suite*          str – e.g. "slack"
        user_task_id*   str – e.g. "user_task_1"
    """
    suite = request.args.get("suite")
    user_task_id = request.args.get("user_task_id")
    if not suite or not user_task_id:
        return jsonify({"error": "Missing query params: suite, user_task_id"}), 400

    try:
        prompt = get_user_task_prompt(suite, user_task_id)
        return jsonify({"suite": suite, "user_task_id": user_task_id, "prompt": prompt}), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "traceback": traceback.format_exc()}), 500


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    """Simple liveness probe."""
    return jsonify({"status": "ok", "active_sessions": len(_sessions)}), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AgentDojo REST API server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    print(f"Starting AgentDojo REST API on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
