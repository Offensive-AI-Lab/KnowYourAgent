"""
Bootstrap one OpenHands conversation per Table-IV repo by cloning a template.

The `openhands --headless` CLI refuses to create new conversations without
interactive settings configured. To stay scriptable we instead clone an
existing, known-good conversation directory (template) and just swap:

  * the conversation `id` (in base_state.json, dashed UUID form),
  * the `persistence_dir` path,
  * the `workspace.working_dir` pointer.

event-00000 (the SystemPromptEvent) is copied verbatim. api.py's init_chat()
will later resume from this fresh state and run the user prompt against the
agent.

Idempotent: skips repos already recorded in pipeline/conversation_ids.json.

Usage:
  python -m benchmarks.openhands.bootstrap                          # all 20
  python -m benchmarks.openhands.bootstrap --repos math-calculator  # one
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Dict, List


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
REPOS_DIR = HERE / "repos"
ORIGINALS_DIR = REPOS_DIR / ".originals"
TASKS_JSON = ORIGINALS_DIR / "tasks.json"
SIDECAR = HERE / "conversation_ids.json"
OH_HOME = Path.home() / ".openhands" / "conversations"


def load_tasks() -> List[Dict]:
    with open(TASKS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)["tasks"]


def load_sidecar() -> List[Dict]:
    if not SIDECAR.exists():
        return []
    with open(SIDECAR, "r", encoding="utf-8") as f:
        return json.load(f)


def save_sidecar(entries: List[Dict]) -> None:
    SIDECAR.parent.mkdir(parents=True, exist_ok=True)
    with open(SIDECAR, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def already_bootstrapped(entries: List[Dict], user_task: str, repo: str) -> bool:
    return any(e["user_task"] == user_task and e["repo"] == repo for e in entries)


def reset_repo(repo: str) -> None:
    src = ORIGINALS_DIR / repo
    dst = REPOS_DIR / repo
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def pick_template(repo: str, entries: List[Dict]) -> str:
    """Return the conversation id of an existing conversation to clone as a template.

    Prefers a conversation for the same repo (keeps the baked workspace path
    correct); falls back to any existing conversation directory.
    """
    same_repo = [e for e in entries if e["repo"] == repo]
    for e in same_repo + entries:
        if (OH_HOME / e["conversation_id"]).is_dir():
            return e["conversation_id"]
    raise FileNotFoundError(
        f"No existing conversation directory found to clone as a template for {repo!r}. "
        "Bootstrap or restore at least one conversation first."
    )


def clone_template_conversation(new_hex_id: str, new_dashed_id: str, workspace_dir: Path,
                                template_conv_id: str) -> None:
    """Create a fresh conversation dir by cloning a template's base_state + event-00000."""
    template_dir = OH_HOME / template_conv_id
    if not template_dir.exists():
        raise FileNotFoundError(f"Template conversation not found at {template_dir}.")
    new_dir = OH_HOME / new_hex_id
    new_dir.mkdir(parents=True, exist_ok=False)
    (new_dir / "events").mkdir()

    # Patch base_state.json
    with open(template_dir / "base_state.json", "r", encoding="utf-8") as f:
        base_state = json.load(f)
    # The template's own workspace path -- substituted out of event-00000 below.
    template_workspace = (base_state.get("workspace") or {}).get("working_dir") or ""
    base_state["id"] = new_dashed_id
    base_state["persistence_dir"] = str(new_dir)
    base_state.setdefault("workspace", {})["working_dir"] = str(workspace_dir)
    base_state["workspace"]["kind"] = base_state["workspace"].get("kind", "LocalWorkspace")
    # Pin the user-agent LLM to gpt-4.1 (paper-canonical target).
    if isinstance(base_state.get("agent"), dict) and isinstance(base_state["agent"].get("llm"), dict):
        base_state["agent"]["llm"]["model"] = "openai/gpt-4.1-2025-04-14"
    # Reset transient run state so the new conv looks fresh.
    # max_iterations defaults to 500 which is way too permissive -- a confused
    # agent can rack up hundreds of tool-call iterations on a one-line task.
    # Cap at 30 so runaway loops bail out quickly.
    base_state["max_iterations"] = 30
    base_state["execution_status"] = "idle"
    base_state["last_user_message_id"] = None
    base_state["activated_knowledge_skills"] = []
    base_state["invoked_skills"] = []
    base_state["blocked_actions"] = {}
    base_state["blocked_messages"] = {}
    with open(new_dir / "base_state.json", "w", encoding="utf-8") as f:
        json.dump(base_state, f, indent=2)

    # Copy event-00000 (the SystemPromptEvent), substituting the template's baked
    # workspace path with our target repo's. Without this the user agent can edit
    # files in the wrong repo, ignoring workspace.working_dir in base_state.json.
    # For a same-repo template the two paths are equal, so this is a no-op.
    template_events = sorted((template_dir / "events").glob("event-00000-*.json"))
    if not template_events:
        raise FileNotFoundError(f"Template has no event-00000 under {template_dir}/events/")
    with open(template_events[0], "r", encoding="utf-8") as f:
        ev0 = json.load(f)
    new_workspace = str(workspace_dir)
    if template_workspace and template_workspace != new_workspace:
        dc = ev0.get("dynamic_context", {})
        if isinstance(dc, dict) and isinstance(dc.get("text"), str):
            dc["text"] = dc["text"].replace(template_workspace, new_workspace)
            ev0["dynamic_context"] = dc
        sp = ev0.get("system_prompt", {})
        if isinstance(sp, dict) and isinstance(sp.get("text"), str):
            sp["text"] = sp["text"].replace(template_workspace, new_workspace)
            ev0["system_prompt"] = sp
    with open(new_dir / "events" / template_events[0].name, "w", encoding="utf-8") as f:
        json.dump(ev0, f, indent=2)


def bootstrap_one(task: Dict, entries: List[Dict]) -> Dict:
    repo = task["repo"]
    user_task = f"user_task_{task['id']}"
    workdir = REPOS_DIR / repo
    if not workdir.exists():
        reset_repo(repo)

    template_conv_id = pick_template(repo, entries)
    new_dashed = str(uuid.uuid4())
    new_hex = new_dashed.replace("-", "")
    clone_template_conversation(new_hex, new_dashed, workdir, template_conv_id)

    print(f"[bootstrap] {repo} ({user_task}) -> {new_hex}  (template: {template_conv_id})")
    return {"user_task": user_task, "repo": repo, "conversation_id": new_hex}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--repos",
        default="all",
        help="Comma-separated repo names (e.g. 'math-calculator,web-todo'), or 'all'.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended actions without writing anything.",
    )
    args = ap.parse_args()

    tasks = load_tasks()
    if args.repos == "all":
        wanted = tasks
    else:
        names = {n.strip() for n in args.repos.split(",") if n.strip()}
        wanted = [t for t in tasks if t["repo"] in names]
        missing = names - {t["repo"] for t in wanted}
        if missing:
            print(f"WARNING: unknown repo(s) ignored: {sorted(missing)}", file=sys.stderr)

    entries = load_sidecar()
    new_count = 0
    for task in wanted:
        user_task = f"user_task_{task['id']}"
        if already_bootstrapped(entries, user_task, task["repo"]):
            print(f"[skip] {task['repo']} already bootstrapped.")
            continue
        if args.dry_run:
            print(f"[dry-run] would bootstrap {task['repo']} ({user_task})")
            continue
        result = bootstrap_one(task, entries)
        entries.append(result)
        save_sidecar(entries)
        new_count += 1

    print(f"\nDone. Wrote {new_count} new entries to {SIDECAR}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
