"""
Read the raw per-pair ChatInject JSONs and emit an Excel workbook that
contains both the Table III summary numbers and every underlying pair.

The point is to make every cell in the summary traceable back to disk —
no hallucination. Open the xlsx in Excel and you can:
  - Sort/filter the `pairs` sheet to see which (user_task, injection_task)
    succeeded under each defense.
  - Verify each summary number by filtering `pairs` and counting manually.

Outputs `table3_chatinject.xlsx` with:
  - `Summary`       — the Table III row (ASR + Δutil per suite + Avg).
  - `Per-suite`     — full per-(defense, suite) stats: ok / files / asr_pct /
                      utility_pct / delta_util / n_security_breached / n_utility_completed.
  - `Pairs`         — every per-pair JSON record, one row per (defense, suite,
                      user_task, injection_task). Includes raw `status`,
                      `security`, `utility`, `duration_s`, `payload_len`,
                      `error` (if any).
  - `Provenance`    — git commit, timestamps, source dirs, mapping from
                      defense label to defense_name string.

Run:
  uv run --with openpyxl --project Benchmarks/agentdojo_edited \
    python chatinject_runs/export_table3_xlsx.py
"""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_LOG_ROOT = Path("runs/chatinject/logs")
_SUITES = ["banking", "slack", "workspace", "travel"]

# (paper_label, dir_suffix, defense_name string passed to AgentDojoChatSession)
_DEFENSES = [
    ("No Defense",    "full",                              None),
    ("PI Detector",   "full_transformers_pi_detector",     "transformers_pi_detector"),
    ("Repeat Prompt", "full_repeat_user_prompt",           "repeat_user_prompt"),
    ("Delimiters",    "full_spotlighting_with_delimiting", "spotlighting_with_delimiting"),
]

_OUT_DIR = Path("runs/chatinject/results")
_OUT_XLSX = _OUT_DIR / "table3_chatinject.xlsx"

_HEADER_FILL = PatternFill("solid", fgColor="305A8C")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_TOTAL_FILL = PatternFill("solid", fgColor="D9E2F3")
_TOTAL_FONT = Font(bold=True)


def _load_pairs() -> list[dict]:
    """Walk every per-pair JSON and return a flat list of dict rows."""
    rows = []
    for label, suffix, defense_name in _DEFENSES:
        for suite in _SUITES:
            suite_dir = _LOG_ROOT / suffix / suite
            if not suite_dir.exists():
                continue
            for fp in sorted(suite_dir.glob("*.json")):
                if fp.name.endswith(".messages.json"):
                    continue
                with open(fp) as f:
                    r = json.load(f)
                rows.append({
                    "defense_label": label,
                    "defense_name": defense_name,
                    "suite": suite,
                    "user_task_id": r.get("user_task_id"),
                    "injection_task_id": r.get("injection_task_id"),
                    "model": r.get("model"),
                    "status": r.get("status"),
                    "security": r.get("security"),
                    "utility": r.get("utility"),
                    "payload_len": r.get("payload_len"),
                    "duration_s": r.get("duration_s"),
                    "error": (r.get("error") or "").split("\n")[0][:300],
                    "json_path": str(fp),
                })
    return rows


def _per_suite_stats(pairs: list[dict]) -> dict[tuple[str, str], dict]:
    """Group by (defense_label, suite) → counts/ASR/utility."""
    out: dict[tuple[str, str], dict] = {}
    for label, _, _ in _DEFENSES:
        for suite in _SUITES:
            subset = [p for p in pairs if p["defense_label"] == label and p["suite"] == suite]
            counts: dict[str, int] = {}
            sec = 0
            util = 0
            for p in subset:
                counts[p["status"]] = counts.get(p["status"], 0) + 1
                if p["status"] == "ok":
                    if p["security"]:
                        sec += 1
                    if p["utility"]:
                        util += 1
            n_ok = counts.get("ok", 0)
            out[(label, suite)] = {
                "files_total": len(subset),
                "counts": counts,
                "n_ok": n_ok,
                "n_security_breached": sec,
                "n_utility_completed": util,
                "asr_pct": (sec / n_ok * 100) if n_ok else None,
                "utility_pct": (util / n_ok * 100) if n_ok else None,
            }
    return out


def _git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parents[3]),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        dirty = subprocess.run(
            ["git", "diff", "--quiet"],
            cwd=str(Path(__file__).resolve().parents[3]),
        ).returncode != 0
        return out + (" (dirty)" if dirty else "")
    except Exception as e:
        return f"unavailable: {e}"


def _style_header_row(ws, row: int, ncols: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _autosize(ws, max_width: int = 60) -> None:
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            v = cell.value
            if v is None:
                continue
            l = len(str(v))
            if l > max_len:
                max_len = l
        ws.column_dimensions[col_letter].width = min(max_len + 2, max_width)


def _build_summary_sheet(ws, stats: dict[tuple[str, str], dict]) -> None:
    ws.append(["Defense", "defense_name passed to AgentDojoChatSession",
               *[f"{s} ASR%" for s in _SUITES], "Avg ASR%",
               *[f"{s} Δutil" for s in _SUITES], "Avg Δutil"])
    _style_header_row(ws, 1, 2 + 2 * len(_SUITES) + 2)

    no_def = {s: stats[("No Defense", s)] for s in _SUITES}
    for label, _, defense_name in _DEFENSES:
        row_asr = [stats[(label, s)]["asr_pct"] for s in _SUITES]
        avg_asr = mean(v for v in row_asr if v is not None) if any(v is not None for v in row_asr) else None

        if label == "No Defense":
            row_delta = [None] * len(_SUITES)
            avg_delta = None
        else:
            row_delta = []
            for s in _SUITES:
                u_def = stats[(label, s)]["utility_pct"]
                u_base = no_def[s]["utility_pct"]
                row_delta.append(
                    (u_def - u_base) if (u_def is not None and u_base is not None) else None
                )
            finite = [v for v in row_delta if v is not None]
            avg_delta = mean(finite) if finite else None

        ws.append([
            label,
            repr(defense_name),
            *[round(v, 1) if v is not None else None for v in row_asr],
            round(avg_asr, 1) if avg_asr is not None else None,
            *[round(v, 1) if v is not None else None for v in row_delta],
            round(avg_delta, 1) if avg_delta is not None else None,
        ])

    # Bold the Avg columns (last ASR avg = col 7, last Δutil avg = col 12)
    for r in range(2, 2 + len(_DEFENSES)):
        ws.cell(row=r, column=2 + len(_SUITES) + 1).font = _TOTAL_FONT
        ws.cell(row=r, column=2 + 2 * len(_SUITES) + 2).font = _TOTAL_FONT

    ws.append([])
    ws.append(["Δutil = utility_pct(defense) - utility_pct(no_defense), per suite. "
               "Avg is unweighted mean across suites."])

    # Also report per-suite utility for transparency
    ws.append([])
    ws.append(["Utility% per (defense, suite)"])
    _style_header_row(ws, ws.max_row, 1)
    ws.append(["Defense", *[f"{s} util%" for s in _SUITES], "Avg util%"])
    _style_header_row(ws, ws.max_row, 1 + len(_SUITES) + 1)
    for label, _, _ in _DEFENSES:
        row = [stats[(label, s)]["utility_pct"] for s in _SUITES]
        avg = mean(v for v in row if v is not None) if any(v is not None for v in row) else None
        ws.append([
            label,
            *[round(v, 1) if v is not None else None for v in row],
            round(avg, 1) if avg is not None else None,
        ])


def _build_per_suite_sheet(ws, stats: dict[tuple[str, str], dict]) -> None:
    ws.append([
        "Defense", "defense_name", "Suite",
        "files_total", "ok", "not_injectable", "no_dialogue", "error",
        "n_security_breached", "n_utility_completed",
        "ASR%", "utility%",
    ])
    _style_header_row(ws, 1, 12)
    for label, _, defense_name in _DEFENSES:
        for s in _SUITES:
            st = stats[(label, s)]
            c = st["counts"]
            ws.append([
                label,
                repr(defense_name),
                s,
                st["files_total"],
                c.get("ok", 0),
                c.get("not_injectable", 0),
                c.get("no_dialogue", 0),
                c.get("error", 0),
                st["n_security_breached"],
                st["n_utility_completed"],
                round(st["asr_pct"], 2) if st["asr_pct"] is not None else None,
                round(st["utility_pct"], 2) if st["utility_pct"] is not None else None,
            ])


def _build_pairs_sheet(ws, pairs: list[dict]) -> None:
    header = ["defense_label", "defense_name", "suite", "user_task_id",
              "injection_task_id", "model", "status", "security", "utility",
              "payload_len", "duration_s", "error", "json_path"]
    ws.append(header)
    _style_header_row(ws, 1, len(header))
    ws.freeze_panes = "A2"
    for p in pairs:
        ws.append([p[k] for k in header])
    ws.auto_filter.ref = ws.dimensions


def _build_provenance_sheet(ws, pairs: list[dict], stats: dict) -> None:
    ws.append(["Key", "Value"])
    _style_header_row(ws, 1, 2)
    rows = [
        ("Generated at (UTC)", datetime.now(timezone.utc).isoformat(timespec="seconds")),
        ("Generated at (epoch)", int(time.time())),
        ("Git commit (PentestingAgent)", _git_commit()),
        ("Model", "gpt-4.1-2025-04-14"),
        ("Attack", "chat_inject_qwen3_with_utility_system_multiturn_7"),
        ("Total per-pair JSONs read", len(pairs)),
        ("Log root", str(_LOG_ROOT)),
        ("Aggregator script", "chatinject_runs/aggregate_with_defenses.py (markdown sibling)"),
        ("This exporter", "chatinject_runs/export_table3_xlsx.py"),
        ("", ""),
        ("Defense label → defense_name string mapping (verbatim):", ""),
    ]
    for label, suffix, defense_name in _DEFENSES:
        rows.append((f"  {label}", f"defense_name = {defense_name!r}; dir = {suffix}/"))
    rows.append(("", ""))
    rows.append(("Suite × user_tasks × injection_tasks:", ""))
    for s in _SUITES:
        total = stats[("No Defense", s)]["files_total"]
        rows.append((f"  {s}", f"{total} pairs"))

    for k, v in rows:
        ws.append([k, v])


def main() -> None:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Reading per-pair JSONs from {_LOG_ROOT} …", flush=True)
    pairs = _load_pairs()
    print(f"  loaded {len(pairs)} per-pair records "
          f"({len(_DEFENSES)} defenses × {len(_SUITES)} suites).")

    stats = _per_suite_stats(pairs)

    # Quick sanity print for the user before writing the xlsx
    print("\nPer-(defense, suite) coverage:")
    for label, _, _ in _DEFENSES:
        for s in _SUITES:
            st = stats[(label, s)]
            c = st["counts"]
            print(f"  {label:<14s} {s:<10s} ok={c.get('ok',0):>4d}  err={c.get('error',0):>2d}  "
                  f"ASR={st['asr_pct']:.2f}%  util={st['utility_pct']:.2f}%")

    wb = Workbook()

    summary_ws = wb.active
    summary_ws.title = "Summary"
    _build_summary_sheet(summary_ws, stats)
    _autosize(summary_ws)

    per_suite_ws = wb.create_sheet("Per-suite")
    _build_per_suite_sheet(per_suite_ws, stats)
    _autosize(per_suite_ws)

    pairs_ws = wb.create_sheet("Pairs")
    _build_pairs_sheet(pairs_ws, pairs)
    _autosize(pairs_ws)

    prov_ws = wb.create_sheet("Provenance")
    _build_provenance_sheet(prov_ws, pairs, stats)
    _autosize(prov_ws)

    wb.save(_OUT_XLSX)
    print(f"\nWrote {_OUT_XLSX}")


if __name__ == "__main__":
    main()
