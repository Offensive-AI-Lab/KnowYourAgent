"""
Export the ChatInject AgentDojo evaluation results to CSV (and XLSX if available).

Reads runs/chatinject/logs/full/{suite}/*.json (every per-attempt result),
emits two files into runs/chatinject/results/:

  - per_attempt.csv : one row per (suite, user_task, injection_task) pair
  - summary.csv     : one row per suite + an Avg. row matching Or's Table II layout

Optionally writes the same data to chatinject_results.xlsx if openpyxl is on
the venv (it's a transitive dep of langchain in this project, so it should be).
"""

import csv
import glob
import json
from pathlib import Path
from statistics import mean

_LOG_ROOT = Path("runs/chatinject/logs/full")
_OUT_ROOT = Path("runs/chatinject/results")
_SUITES = ["banking", "slack", "workspace", "travel"]  # Or's Table II order


def _per_attempt_rows() -> list[dict]:
    rows = []
    for suite in _SUITES:
        for fp in sorted(glob.glob(str(_LOG_ROOT / suite / "*.json"))):
            if fp.endswith(".messages.json"):
                continue
            with open(fp) as f:
                r = json.load(f)
            rows.append({
                "suite": suite,
                "user_task_id": r.get("user_task_id"),
                "injection_task_id": r.get("injection_task_id"),
                "model": r.get("model"),
                "status": r.get("status"),
                "security": r.get("security"),
                "utility": r.get("utility"),
                "payload_len": r.get("payload_len"),
                "duration_s": round(r.get("duration_s", 0), 3),
                "injection_candidates": ",".join(r.get("injection_candidates", []) or []),
                "error": r.get("error", ""),
            })
    return rows


def _summary_rows(per_attempt: list[dict]) -> list[dict]:
    rows = []
    for suite in _SUITES:
        suite_rows = [r for r in per_attempt if r["suite"] == suite]
        ok_rows = [r for r in suite_rows if r["status"] == "ok"]
        n_ok = len(ok_rows)
        breached = sum(1 for r in ok_rows if r["security"] is True)
        util_pass = sum(1 for r in ok_rows if r["utility"] is True)
        asr = (breached / n_ok * 100) if n_ok else 0.0
        utility = (util_pass / n_ok * 100) if n_ok else 0.0
        durs = [r["duration_s"] for r in ok_rows]
        rows.append({
            "suite": suite,
            "n_total": len(suite_rows),
            "n_ok": n_ok,
            "n_breached": breached,
            "n_util_pass": util_pass,
            "asr_pct": round(asr, 2),
            "utility_pct": round(utility, 2),
            "avg_duration_s": round(mean(durs) if durs else 0, 2),
        })

    rows.append({
        "suite": "Avg.",
        "n_total": sum(r["n_total"] for r in rows),
        "n_ok": sum(r["n_ok"] for r in rows),
        "n_breached": sum(r["n_breached"] for r in rows),
        "n_util_pass": sum(r["n_util_pass"] for r in rows),
        "asr_pct": round(mean(r["asr_pct"] for r in rows), 2),
        "utility_pct": round(mean(r["utility_pct"] for r in rows), 2),
        "avg_duration_s": round(mean(r["avg_duration_s"] for r in rows), 2),
    })
    return rows


def main() -> None:
    _OUT_ROOT.mkdir(parents=True, exist_ok=True)

    per_attempt = _per_attempt_rows()
    summary = _summary_rows(per_attempt)

    # per_attempt.csv
    pa_path = _OUT_ROOT / "per_attempt.csv"
    with open(pa_path, "w", newline="") as f:
        if per_attempt:
            writer = csv.DictWriter(f, fieldnames=list(per_attempt[0].keys()))
            writer.writeheader()
            writer.writerows(per_attempt)
    print(f"Wrote {pa_path} ({len(per_attempt)} rows)")

    # summary.csv
    sum_path = _OUT_ROOT / "summary.csv"
    with open(sum_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        writer.writerows(summary)
    print(f"Wrote {sum_path} ({len(summary)} rows)")

    # XLSX if openpyxl available
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws_summary = wb.active
        ws_summary.title = "summary"
        if summary:
            ws_summary.append(list(summary[0].keys()))
            for row in summary:
                ws_summary.append([row[k] for k in summary[0].keys()])
        ws_attempts = wb.create_sheet("per_attempt")
        if per_attempt:
            ws_attempts.append(list(per_attempt[0].keys()))
            for row in per_attempt:
                ws_attempts.append([row[k] for k in per_attempt[0].keys()])
        xlsx_path = _OUT_ROOT / "chatinject_results.xlsx"
        wb.save(xlsx_path)
        print(f"Wrote {xlsx_path}")
    except ImportError:
        print("(openpyxl not available — skipped XLSX. CSVs are sufficient.)")

    # Print summary to stdout (for the user to eyeball)
    print()
    print("=" * 78)
    print("SUMMARY (also in summary.csv)")
    print("=" * 78)
    hdr = ["suite", "n_total", "n_ok", "n_breached", "asr_pct", "utility_pct", "avg_duration_s"]
    print(f"{'suite':<11} {'n_total':>8} {'n_ok':>6} {'n_breached':>10} {'asr_pct':>9} {'utility_pct':>11} {'avg_dur_s':>10}")
    print("-" * 78)
    for row in summary:
        print(f"{row['suite']:<11} {row['n_total']:>8} {row['n_ok']:>6} "
              f"{row['n_breached']:>10} {row['asr_pct']:>9} "
              f"{row['utility_pct']:>11} {row['avg_duration_s']:>10}")

    print()
    print("=" * 78)
    print("Sanity check — manual recomputation per suite:")
    print("=" * 78)
    for row in summary[:-1]:
        recomputed = (row["n_breached"] / row["n_ok"] * 100) if row["n_ok"] else 0
        print(f"  {row['suite']}: {row['n_breached']} / {row['n_ok']} = {recomputed:.4f}%  "
              f"(matches asr_pct in summary: {abs(recomputed - row['asr_pct']) < 0.01})")


if __name__ == "__main__":
    main()
