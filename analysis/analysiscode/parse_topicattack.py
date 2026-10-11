"""
Parse TopicAttack experiment result files into a DataFrame.

Each .txt file in a suite folder contains results for one injection task
across multiple user tasks. The parser extracts per-entry security and
utility booleans.

Usage:
    from analysis.analysiscode.parse_topicattack import collect_topicattack_rows
    rows = collect_topicattack_rows([
        "Experiments/TopicAttack/AgentDojo/banking",
        "Experiments/TopicAttack/AgentDojo/travel",
    ])
    df = pd.DataFrame(rows)
"""

import re
from pathlib import Path

import pandas as pd

# Patterns for the structured log lines
_ENTRY_RE = re.compile(
    r"Entry\s+\d+/\d+\s+\|\s+user_task=(\S+)\s+\|\s+injection_task=(\S+)"
)
_SECURITY_RE = re.compile(r"security \(attack succeeded\):\s*(True|False)")
_UTILITY_RE = re.compile(r"utility\s+\(task completed\)\s*:\s*(True|False)")
_SUITE_RE = re.compile(r"'suite_name':\s*'(\w+)'")


def parse_topicattack_file(filepath: str) -> list[dict]:
    """Parse a single TopicAttack .txt log file.

    Returns a list of dicts, one per entry, with keys:
        user_task, injection_task, security, utility
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    entries: list[dict] = []
    current: dict | None = None

    for line in content.splitlines():
        entry_m = _ENTRY_RE.search(line)
        if entry_m:
            current = {
                "user_task": entry_m.group(1),
                "injection_task": entry_m.group(2),
                "security": None,
                "utility": None,
            }
            entries.append(current)
            continue

        if current is None:
            continue

        sec_m = _SECURITY_RE.search(line)
        if sec_m:
            current["security"] = sec_m.group(1) == "True"
            continue

        util_m = _UTILITY_RE.search(line)
        if util_m:
            current["utility"] = util_m.group(1) == "True"
            continue

    return entries


def collect_topicattack_rows(
    suite_folders: list[str],
    benchmark: str = "agentdojo",
) -> list[dict]:
    """Walk suite folders and parse every .txt file into rows.

    Args:
        suite_folders: Paths to suite directories (e.g.
            ``Experiments/TopicAttack/AgentDojo/banking``).
            Each folder should contain ``*_ij*.txt`` or ``ij*.txt`` files.
        benchmark: Benchmark label to attach to every row.

    Returns:
        List of dicts with keys: benchmark, suite, user_task,
        injection_task, security, utility.
    """
    rows: list[dict] = []
    for folder in suite_folders:
        folder = Path(folder)
        suite_name = folder.name

        for txt_file in sorted(folder.glob("*.txt")):
            entries = parse_topicattack_file(str(txt_file))
            for entry in entries:
                rows.append({
                    "benchmark": benchmark,
                    "suite": suite_name,
                    "user_task": entry["user_task"],
                    "injection_task": entry["injection_task"],
                    "security": entry["security"],
                    "utility": entry["utility"],
                })
    return rows


def topicattack_asr_by_suite(
    suite_folders: list[str],
    benchmark: str = "agentdojo",
) -> pd.DataFrame:
    """Return a DataFrame with per-suite ASR and utility accuracy.

    Columns: suite, asr, utility_accuracy, total
    """
    rows = collect_topicattack_rows(suite_folders, benchmark=benchmark)
    if not rows:
        return pd.DataFrame(columns=["suite", "asr", "utility_accuracy", "total"])

    df = pd.DataFrame(rows)
    stats = df.groupby("suite").agg(
        asr=("security", lambda x: x.sum() / len(x) * 100),
        utility_accuracy=("utility", lambda x: x.sum() / len(x) * 100),
        total=("security", "count"),
    ).reset_index()
    return stats
