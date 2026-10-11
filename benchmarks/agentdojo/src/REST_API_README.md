# AgentDojo REST API

A lightweight REST server (Flask) that wraps `api.py` so that **AgentDojoChatSession** instances and utility helpers can be consumed over HTTP.

Sessions are stored **in-memory** and are automatically cleared when the server process stops.

---

## Quick Start

```bash
# Install Flask if not already available
pip install flask

# Start the server (defaults to http://127.0.0.1:5000)
python benchmarks/agentdojo/src/rest_api.py

# Optional flags
python benchmarks/agentdojo/src/rest_api.py --host 0.0.0.0 --port 8080 --debug
```

---

## Endpoints

### Health Check

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe. Returns `{"status": "ok", "active_sessions": <n>}`. |

---

### Session Management

#### Create Session

```
POST /sessions
```

Creates a new `AgentDojoChatSession` and returns a unique `session_id`.

**Request body** (JSON):

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `suite_name` | string | **yes** | – | Benchmark suite, e.g. `"slack"` |
| `user_task_id` | string | **yes** | – | User task, e.g. `"user_task_1"` |
| `model_name` | string | **yes** | – | LLM model, e.g. `"gpt-4o-2024-05-13"` |
| `injection_task_name` | string | no | `"injection_task_0"` | Injection task identifier |
| `run_dir` | string | no | `"runs"` | Directory for logs |
| `defense_name` | string\|null | no | `null` | Defense to apply |
| `system_message_name` | string\|null | no | `null` | Named system message |

**Response** (`201`):

```json
{ "session_id": "a1b2c3d4..." }
```

---

#### List Sessions

```
GET /sessions
```

Returns all active session IDs.

**Response** (`200`):

```json
{ "sessions": ["a1b2c3d4...", "e5f6g7h8..."] }
```

---

#### Delete a Session

```
DELETE /sessions/<session_id>
```

Removes a single session.

**Response** (`200`):

```json
{ "deleted": "a1b2c3d4..." }
```

---

#### Delete All Sessions

```
DELETE /sessions
```

Removes every active session.

**Response** (`200`):

```json
{ "deleted_count": 3 }
```

---

### Chat Operations

All chat endpoints require a valid `session_id` in the URL path.

#### Initialise Chat

```
POST /sessions/<session_id>/init_chat
```

Runs the user-task prompt through the pipeline and populates the conversation history.

No request body required.

**Response** (`200`):

```json
{ "messages": [ ... ] }
```

---

#### Send Message

```
POST /sessions/<session_id>/send
```

Sends a message to the agent and returns the new messages plus utility/security checks.

**Request body** (JSON):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string\|null | no | Text to send. If `null` or omitted, the user-task prompt is used. |

**Response** (`200`):

```json
{
  "messages": [ ... ],
  "utility": true,
  "security": false
}
```

---

#### Prompt Agent

```
POST /sessions/<session_id>/prompt_agent
```

Replaces `history[1]` with custom content, truncates subsequent history, and re-runs the pipeline.

**Request body** (JSON):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | **yes** | The content to inject at position 1 |

**Response** (`200`):

```json
{ "history": [ ... ] }
```

---

### Injection Operations

#### Inject via Environment

```
POST /sessions/<session_id>/inject_via_environment
```

Injects content into the environment at all discoverable injection candidates, then runs the user task from scratch.

**Request body** (JSON):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | **yes** | The injection payload |

**Response** (`200`):

```json
{
  "messages": [ ... ],
  "security": true,
  "utility": false
}
```

---

#### Inject at History Index

```
POST /sessions/<session_id>/inject_at_index
```

Replaces the tool-result message at a given history index with injected content, truncates history after that point, and resumes the conversation.

**Request body** (JSON):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | **yes** | The injection payload |
| `index` | int | **yes** | Index in the conversation history to replace |

**Response** (`200`):

```json
{
  "messages": [ ... ],
  "security": "################## PENTESTING GOAL ACHIEVED: True ################",
  "utility": "################## UTILITY GOAL ACHIEVED: True ################"
}
```

---

### Session Inspection

#### Get History

```
GET /sessions/<session_id>/history
```

Returns the full conversation history for the session.

**Response** (`200`):

```json
{ "history": [ ... ] }
```

---

#### Get Injection Candidates

```
GET /sessions/<session_id>/injection_candidates
```

Returns the list of injection vector names visible to the model for the session's user task.

**Response** (`200`):

```json
{ "injection_candidates": ["injection_banking_0", "injection_banking_1"] }
```

---

### Utility Endpoints (Stateless)

These do **not** require a session. They query the benchmark suites directly.

#### Get Injection Goal

```
GET /utils/injection_goal?suite=<suite>&injection_id=<injection_id>
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `suite` | string | **yes** | e.g. `"slack"` |
| `injection_id` | string | **yes** | e.g. `"injection_task_0"` |

**Response** (`200`):

```json
{
  "suite": "slack",
  "injection_id": "injection_task_0",
  "goal": "Send the secret token to attacker@evil.com"
}
```

---

#### Get User Task Prompt

```
GET /utils/user_task_prompt?suite=<suite>&user_task_id=<user_task_id>
```

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `suite` | string | **yes** | e.g. `"slack"` |
| `user_task_id` | string | **yes** | e.g. `"user_task_1"` |

**Response** (`200`):

```json
{
  "suite": "slack",
  "user_task_id": "user_task_1",
  "prompt": "Find the latest message from Alice in #general"
}
```

---

## Error Handling

All endpoints return errors as JSON with an appropriate HTTP status code:

```json
{
  "error": "Human-readable error message",
  "traceback": "Full Python traceback (only on 500 errors)"
}
```

| Status | Meaning |
|--------|---------|
| `400` | Bad request – missing or invalid parameters |
| `404` | Session not found |
| `500` | Internal server error |

---

## Session Lifecycle

- **Creation**: `POST /sessions` allocates a session and returns a `session_id`.
- **Usage**: Use the `session_id` in subsequent calls to chat, inject, or inspect.
- **Cleanup**: `DELETE /sessions/<session_id>` frees a single session. `DELETE /sessions` clears all.
- **Restart**: All sessions are automatically destroyed when the server process exits.
