"""
Aggregate ChatInject results across the No-Defense baseline + 3 defenses into
the Table III row of the ACSAC paper.

Reads from:
  runs/chatinject/logs/full/{suite}/                         (no defense, existing)
  runs/chatinject/logs/full_transformers_pi_detector/{suite}/
  runs/chatinject/logs/full_repeat_user_prompt/{suite}/
  runs/chatinject/logs/full_spotlighting_with_delimiting/{suite}/

For each (suite, defense), computes ASR (% of ok pairs where security=True)
and utility_pct (% of ok pairs where utility=True). Δutil is utility_pct under
defense minus utility_pct under no defense, per suite.

Emits:
  runs/chatinject/results/table3_chatinject.md
  runs/chatinject/results/table3_chatinject.json
"""

import json
from pathlib import Path
from statistics import mean

_LOG_ROOT = Path("runs/chatinject/logs")
_SUITES = ["banking", "slack", "workspace", "travel"]
_OUT_DIR = Path("runs/chatinject/results")
_OUT_MD = _OUT_DIR / "table3_chatinject.md"
_OUT_JSON = _OUT_DIR / "table3_chatinject.json"

# (paper_label, dir_suffix, defense_name string passed to AgentDojoChatSession)
_DEFENSES = [
    ("No Defense",    "full",                              None),
    ("PI Detector",   "full_transformers_pi_detector",     "transformers_pi_detector"),
    ("Repeat Prompt", "full_repeat_user_prompt",           "repeat_user_prompt"),
    ("Delimiters",    "full_spotlighting_with_delimiting", "spotlighting_with_delimiting"),
]


def _suite_stats(root: Path, suite: str) -> dict:
    suite_dir = root / suite
    if not suite_dir.exists():
        return {"suite": suite, "n_ok": 0, "asr_pct": None, "utility_pct": None,
                "counts": {}, "files_total": 0, "missing": True}
    files = sorted(p for p in suite_dir.glob("*.json")
                   if not p.name.endswith(".messages.json"))
    counts: dict[str, int] = {}
    sec_true = 0
    util_true = 0
    for fp in files:
        with open(fp) as f:
            r = json.load(f)
        status = r.get("status", "other")
        counts[status] = counts.get(status, 0) + 1
        if status == "ok":
            if r.get("security"):
                sec_true += 1
            if r.get("utility"):
                util_true += 1
    n_ok = counts.get("ok", 0)
    return {
        "suite": suite,
        "n_ok": n_ok,
        "asr_pct": (sec_true / n_ok * 100) if n_ok else None,
        "utility_pct": (util_true / n_ok * 100) if n_ok else None,
        "n_security_breached": sec_true,
        "n_utility_completed": util_true,
        "counts": counts,
        "files_total": len(files),
        "missing": False,
    }


def main() -> None:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    # rows[defense_label][suite] = stats dict
    rows: dict[str, dict[str, dict]] = {}
    for label, suffix, _ in _DEFENSES:
        rows[label] = {s: _suite_stats(_LOG_ROOT / suffix, s) for s in _SUITES}

    no_defense = rows["No Defense"]

    def _avg(values):
        finite = [v for v in values if v is not None]
        return mean(finite) if finite else None

    def _fmt(v, suffix="%"):
        return "n/a" if v is None else f"{v:.1f}{suffix}"

    def _fmt_delta(v):
        if v is None:
            return "n/a"
        return f"{v:+.1f}"

    md = []
    md.append("# Table III — ChatInject vs. defenses")
    md.append("")
    md.append("Model: `gpt-4.1-2025-04-14`")
    md.append(f"Source dirs (root = `{_LOG_ROOT}`):")
    for label, suffix, defense_name in _DEFENSES:
        md.append(f"  - **{label}**  →  `{suffix}/`  →  `defense_name = {defense_name!r}`")
    md.append("")
    md.append("## Table III row (ChatInject)")
    md.append("")
    md.append("| Defense | banking ASR | slack ASR | workspace ASR | travel ASR | Avg ASR | banking Δutil | slack Δutil | workspace Δutil | travel Δutil | Avg Δutil |")
    md.append("|---------|-------------|-----------|---------------|------------|---------|---------------|-------------|-----------------|--------------|-----------|")

    for label, suffix, _ in _DEFENSES:
        suite_rows = rows[label]
        asr_per_suite = {s: suite_rows[s]["asr_pct"] for s in _SUITES}
        avg_asr = _avg(asr_per_suite.values())

        if label == "No Defense":
            delta_per_suite = {s: None for s in _SUITES}
            avg_delta = None
        else:
            delta_per_suite = {}
            for s in _SUITES:
                u_def = suite_rows[s]["utility_pct"]
                u_base = no_defense[s]["utility_pct"]
                delta_per_suite[s] = (u_def - u_base) if (u_def is not None and u_base is not None) else None
            avg_delta = _avg(delta_per_suite.values())

        md.append(
            f"| {label} "
            f"| {_fmt(asr_per_suite['banking'])} "
            f"| {_fmt(asr_per_suite['slack'])} "
            f"| {_fmt(asr_per_suite['workspace'])} "
            f"| {_fmt(asr_per_suite['travel'])} "
            f"| **{_fmt(avg_asr)}** "
            f"| {_fmt_delta(delta_per_suite['banking'])} "
            f"| {_fmt_delta(delta_per_suite['slack'])} "
            f"| {_fmt_delta(delta_per_suite['workspace'])} "
            f"| {_fmt_delta(delta_per_suite['travel'])} "
            f"| **{_fmt_delta(avg_delta)}** |"
        )

    md.append("")
    md.append("Δutil = utility_pct(defense) - utility_pct(no_defense), per suite. "
              "Avg is the unweighted mean across suites (matches Table II convention). "
              "Utility_pct here = fraction of `ok` pairs where the agent completed "
              "the user's original task while under attack.")
    md.append("")
    md.append("## Per-(defense, suite) utility")
    md.append("")
    md.append("| Defense | banking util | slack util | workspace util | travel util | Avg util |")
    md.append("|---------|--------------|------------|----------------|-------------|----------|")
    for label, _, _ in _DEFENSES:
        suite_rows = rows[label]
        util_per_suite = {s: suite_rows[s]["utility_pct"] for s in _SUITES}
        md.append(
            f"| {label} "
            f"| {_fmt(util_per_suite['banking'])} "
            f"| {_fmt(util_per_suite['slack'])} "
            f"| {_fmt(util_per_suite['workspace'])} "
            f"| {_fmt(util_per_suite['travel'])} "
            f"| **{_fmt(_avg(util_per_suite.values()))}** |"
        )

    md.append("")
    md.append("## Coverage (per-suite ok / files / not_injectable / errors)")
    md.append("")
    md.append("| Defense | Suite | ok | not_injectable | no_dialogue | error | files |")
    md.append("|---------|-------|----|----|------|-------|-------|")
    for label, _, _ in _DEFENSES:
        for s in _SUITES:
            r = rows[label][s]
            c = r["counts"]
            md.append(
                f"| {label} | {s} | {c.get('ok',0)} | {c.get('not_injectable',0)} | "
                f"{c.get('no_dialogue',0)} | {c.get('error',0)} | {r['files_total']} |"
            )

    out_md = "\n".join(md) + "\n"
    _OUT_MD.write_text(out_md)

    payload = {
        "model": "gpt-4.1-2025-04-14",
        "attack": "chat_inject_qwen3_with_utility_system_multiturn_7",
        "defenses": [
            {"label": label, "dir": suffix, "defense_name": defense_name}
            for (label, suffix, defense_name) in _DEFENSES
        ],
        "rows": rows,
    }
    _OUT_JSON.write_text(json.dumps(payload, indent=2))

    print(out_md)
    print(f"Wrote {_OUT_MD}")
    print(f"Wrote {_OUT_JSON}")


if __name__ == "__main__":
    main()
