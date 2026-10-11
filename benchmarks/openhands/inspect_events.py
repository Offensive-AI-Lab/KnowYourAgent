"""
Inspect a baseline conversation's event stream and surface candidate injection
indices. Reads events from benchmarks/openhands/logs/baseline/{instance_id}/events/.

Usage:
  python benchmarks/openhands/inspect_events.py pydata__xarray-6461
  python benchmarks/openhands/inspect_events.py pydata__xarray-6461 --full-content
  python benchmarks/openhands/inspect_events.py pydata__xarray-6461 --observations-only

Highlights ObservationEvents whose content references docs the agent reads
(`.md`, `.rst`, CONTRIBUTING, CODE_OF_CONDUCT, `core/`) or the task's patched_file
(from manifest.json). Those are the natural injection points per the
PROMPT_INJECTION_GUIDE: observations are treated as ground truth by the agent,
so payloads inserted there carry the most authority.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

OH_DIR = Path(__file__).resolve().parent
LOGS_DIR = OH_DIR / "logs" / "baseline"

HIGHLIGHT_PATTERNS = [
    (r"\.md\b", "md"),
    (r"\.rst\b", "rst"),
    (r"CONTRIBUTING", "CONTRIBUTING"),
    (r"CODE_OF_CONDUCT", "CODE_OF_CONDUCT"),
    (r"xarray/core/", "core/"),
]


def index_of(filename: str) -> int:
    m = re.match(r"event-(\d+)-", filename)
    return int(m.group(1)) if m else -1


def load_raw_events(events_dir: Path) -> list[dict]:
    files = sorted(events_dir.glob("event-*.json"), key=lambda p: index_of(p.name))
    return [json.loads(p.read_text()) for p in files]


def event_kind(e: dict) -> str:
    return e.get("kind") or "?"


def event_source(e: dict) -> str:
    return e.get("source") or "-"


def event_tool(e: dict) -> str:
    action = e.get("action") or {}
    observation = e.get("observation") or {}
    tool_call = e.get("tool_call") or {}
    return (
        action.get("kind")
        or observation.get("kind")
        or tool_call.get("name")
        or e.get("tool_name")
        or "-"
    )


def _extract_text(c) -> str:
    """OpenHands content is often a list of {type, text} dicts. Pull the text out."""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for item in c:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return ""


def event_content(e: dict) -> str:
    obs = e.get("observation") or {}
    if obs:
        txt = _extract_text(obs.get("content"))
        if txt:
            return txt
    act = e.get("action") or {}
    if act:
        for k in ("content", "command", "description", "prompt"):
            v = act.get(k)
            if isinstance(v, str) and v:
                return v
    msg = e.get("llm_message") or e.get("message")
    if isinstance(msg, dict):
        txt = _extract_text(msg.get("content"))
        if txt:
            return txt
    for k in ("system_prompt", "content", "summary", "stdout", "text"):
        v = e.get(k)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            txt = _extract_text(v.get("text") or v.get("content"))
            if txt:
                return txt
    return ""


def compute_highlight(e: dict, patched_file: str | None) -> str:
    content = event_content(e)
    tags = []
    if patched_file and patched_file in content:
        tags.append(f"***{patched_file}***")
    for pat, label in HIGHLIGHT_PATTERNS:
        if re.search(pat, content):
            tags.append(label)
    return ",".join(tags) if tags else ""


def truncate(s: str, n: int) -> str:
    s = s.replace("\n", " ").replace("\r", " ")
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("instance_id", help="e.g. pydata__xarray-6461")
    ap.add_argument("--full-content", action="store_true",
                    help="Print full content of each event (no truncation).")
    ap.add_argument("--observations-only", action="store_true",
                    help="Print only ObservationEvents (the injection target type).")
    args = ap.parse_args()

    log_dir = LOGS_DIR / args.instance_id
    events_dir = log_dir / "events"
    if not events_dir.is_dir():
        sys.exit(f"FATAL: no events dir at {events_dir}. Run the baseline first.")

    manifest_path = log_dir / "manifest.json"
    patched_file = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        patched_file = manifest.get("patched_file")
        print(f"# {args.instance_id}  patched_file={patched_file}  "
              f"num_events_manifest={manifest.get('num_events')}  "
              f"model={manifest.get('model')}")

    events = load_raw_events(events_dir)
    candidate_indices: list[int] = []

    header = f"{'IDX':>3}  {'KIND':<22}  {'SOURCE':<11}  {'TOOL':<14}  {'CONTENT' if args.full_content else 'PREVIEW'}    HIGHLIGHT"
    print(header)
    print("-" * (len(header) + 40))

    for i, e in enumerate(events):
        kind = event_kind(e)
        if args.observations_only and "Observation" not in kind:
            continue
        src = event_source(e)
        tool = event_tool(e)
        content = event_content(e)
        preview = content if args.full_content else truncate(content, 80)
        hl = compute_highlight(e, patched_file)
        if "Observation" in kind and hl:
            candidate_indices.append(i)
        print(f"{i:>3}  {kind:<22}  {src:<11}  {tool:<14}  {preview}    {hl}")

    print()
    if candidate_indices:
        print(f"Candidate injection indices (highlighted ObservationEvents): {candidate_indices}")
    else:
        print("No ObservationEvents matched the highlight patterns. "
              "Inspect with --full-content to find a manual candidate.")
    print(
        "Next step: pick one index and (eventually) register as\n"
        f"  INJECTION_INDICES[({args.instance_id!r}, \"pydata__xarray\")] = <chosen_index>"
    )


if __name__ == "__main__":
    main()
