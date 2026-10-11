"""
Extract injection payloads from experiment log files.

Walks the Experiments/ directory, finds all .ans files under
banking/travel/workspace/slack suites, and extracts the "content"
field from every "Execute the attack" agent Final Answer.

Results are organized by (suite, injection_task, user_task) and
saved to a JSON file.
"""

import json
import os
import re
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent / "Experiments"
OUTPUT_PATH = Path(__file__).resolve().parent / "extracted_payloads.json"

SUITES = {"banking", "travel", "workspace", "slack"}

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# Path parsing
# ---------------------------------------------------------------------------

def parse_path_info(filepath: Path):
    """Return (suite, injection_task, user_task, experiment_variant) or None.

    experiment_variant encodes the path segments between the experiment
    root folder and the suite folder (e.g. "CobraV3/AgentDojo").
    """
    parts = filepath.parts

    # Locate the Experiments root
    try:
        exp_idx = parts.index("Experiments")
    except ValueError:
        return None

    # Find the suite folder
    suite = None
    suite_idx = None
    for i in range(exp_idx + 1, len(parts)):
        if parts[i] in SUITES:
            suite = parts[i]
            suite_idx = i
            break

    if suite is None:
        return None

    # The variant is everything between Experiments/ and the suite folder
    variant = "/".join(parts[exp_idx + 1 : suite_idx])

    # Next folder after suite should be ij<N>
    if suite_idx + 1 >= len(parts):
        return None
    ij_match = re.match(r"ij(\d+)", parts[suite_idx + 1])
    if not ij_match:
        return None
    injection_task = int(ij_match.group(1))

    # User task from filename (ut_<N>.ans or ut_<N>_ij_<M>.ans)
    filename = filepath.stem
    ut_match = re.match(r"ut_(\d+)", filename)
    if not ut_match:
        return None
    user_task = int(ut_match.group(1))

    return suite, injection_task, user_task, variant


# ---------------------------------------------------------------------------
# Payload extraction
# ---------------------------------------------------------------------------

def extract_payloads(filepath: Path) -> list[str]:
    """Return list of payload content strings from Execute‑the‑attack answers."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    clean = strip_ansi(raw)
    payloads = []

    # Strategy: find every occurrence of
    #   # Agent: Execute the attack
    #   ## Final Answer:
    # and grab the text that follows until the next section boundary.

    # Build a list of all "# Agent:" positions so we can delimit sections.
    agent_starts = [m.start() for m in re.finditer(r"^# Agent:", clean, re.MULTILINE)]

    for i, start in enumerate(agent_starts):
        # Grab section header line
        line_end = clean.index("\n", start)
        header = clean[start:line_end].strip()

        if "Execute the attack" not in header:
            continue

        # Determine the end of this agent's block (next "# Agent:" or EOF)
        section_end = agent_starts[i + 1] if i + 1 < len(agent_starts) else len(clean)
        section = clean[start:section_end]

        # Look for "## Final Answer:" inside this section
        fa_match = re.search(r"## Final Answer:\s*\n", section)
        if not fa_match:
            continue

        answer_start = fa_match.end()

        # The answer text runs until the next major delimiter inside the
        # section, or until the section ends.
        # Possible delimiters: another "## " heading,  "[+]" / "[-]" lines,
        # "=== Flow Finished ===" , bare "[{" indicating the conversation log.
        end_match = re.search(
            r"\n(?=## |\[\+\]|\[\-\]|=== Flow|Security \(|\[{)",
            section[answer_start:],
        )
        if end_match:
            answer_text = section[answer_start : answer_start + end_match.start()]
        else:
            answer_text = section[answer_start:]

        answer_text = answer_text.strip()

        content = _extract_content_field(answer_text)
        if content is not None:
            payloads.append(content)

    return payloads


def _extract_content_field(answer_text: str):
    """Try to pull the 'content' value out of a Final Answer block."""
    # Strip markdown code fences if present
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)```", answer_text, re.DOTALL)
    json_candidate = fenced.group(1).strip() if fenced else answer_text.strip()

    # Try direct JSON parse
    parsed = _try_parse_json(json_candidate)
    if parsed is not None:
        return parsed

    # Fallback: try to locate the outermost { ... } containing "content"
    brace_match = re.search(r"\{.*\"content\".*\}", json_candidate, re.DOTALL)
    if brace_match:
        parsed = _try_parse_json(brace_match.group(0))
        if parsed is not None:
            return parsed

    return None


def _try_parse_json(text: str):
    """Parse JSON and return the 'content' value, or None."""
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "content" in data:
            return data["content"]
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    results = defaultdict(list)
    files_processed = 0
    files_with_payloads = 0

    for ans_file in sorted(BASE_DIR.rglob("*.ans")):
        info = parse_path_info(ans_file)
        if info is None:
            continue

        suite, ij, ut, variant = info
        files_processed += 1

        payloads = extract_payloads(ans_file)
        if payloads:
            files_with_payloads += 1

        key = (suite, ij, ut)
        for payload in payloads:
            results[key].append(
                {
                    "payload": payload,
                    "source_file": str(ans_file.relative_to(BASE_DIR)),
                    "experiment": variant,
                }
            )

    # Build JSON-friendly output keyed by "suite/ij<N>/ut_<M>"
    output = {}
    for (suite, ij, ut), entries in sorted(results.items()):
        key_str = f"{suite}/ij{ij}/ut_{ut}"
        output[key_str] = entries

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Summary
    total_payloads = sum(len(v) for v in output.values())
    print(f"Files processed:  {files_processed}")
    print(f"Files w/ payloads: {files_with_payloads}")
    print(f"Total payloads:   {total_payloads}")
    print(f"Unique (suite, ij, ut) keys: {len(output)}")
    print(f"Output saved to:  {OUTPUT_PATH}")

    # Per-suite breakdown
    suite_counts = defaultdict(int)
    for (suite, _, _), entries in results.items():
        suite_counts[suite] += len(entries)
    for s in sorted(suite_counts):
        print(f"  {s}: {suite_counts[s]} payloads")


if __name__ == "__main__":
    main()
