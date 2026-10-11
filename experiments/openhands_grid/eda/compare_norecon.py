#!/usr/bin/env python3
"""Compare a NoRecon (recon disabled) ablation run against the pooled 3-pass
FullAgent baseline of the 7x10 Cobra-vs-OpenHands grid.

NoRecon is currently a single pass (70 cells); FullAgent is pooled across 3
independent passes (210 cells). The two are NOT equal-sample-size -- this
script reports both denominators explicitly rather than blending them into
one rate. Does not modify aggregate_passes.py or check_consistency.py; only
imports their reusable pieces.

Reads:
  FullAgent baseline -- same 3 sources as eda/aggregate_passes.py:
    pass1 -> results/COMBINED_SUMMARY.md
    pass2 -> results/cobra_openhands_20260524_170814/summary.txt
    pass3 -> results/cobra_openhands_20260524_230606/summary.txt (+ pass3_patch* dirs)
  NoRecon run -- <run_dir>/summary.txt (path given as a CLI arg; defaults to
    the newest results/norecon_cobra_openhands_* dir)

Writes:
  eda/norecon/compare_norecon.md              human-readable report
  eda/norecon/per_cell_norecon_vs_full.csv     tidy per-cell rows

Usage:
    uv run python cobra_runs/eda/compare_norecon.py [run_dir]
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aggregate_passes import (  # noqa: E402
    PAIRS, INJECTIONS, ROSTER, RESULTS,
    PASS2_DIR, PASS3_DIR,
    parse_summary, parse_combined, find_pass3_patches,
)

OUT = Path(__file__).resolve().parent / "norecon"
PASS_NAMES = ["pass1", "pass2", "pass3"]


def load_fullagent_passes() -> tuple:
    """Returns (passes, missing) -- missing lists pass names whose source dir/file
    isn't present on this checkout (e.g. pass2/pass3 only ever ran on the cluster
    and were never synced locally), so callers can flag an under-populated baseline
    instead of silently treating 0 measured cells as "pass had no successes"."""
    missing = []
    if not (RESULTS / "COMBINED_SUMMARY.md").exists():
        missing.append("pass1 (COMBINED_SUMMARY.md not found)")
    if not (PASS2_DIR / "summary.txt").exists():
        missing.append(f"pass2 ({PASS2_DIR.name} not found)")
    if not (PASS3_DIR / "summary.txt").exists():
        missing.append(f"pass3 ({PASS3_DIR.name} not found)")
    passes = {
        "pass1": parse_combined(RESULTS / "COMBINED_SUMMARY.md"),
        "pass2": parse_summary(PASS2_DIR / "summary.txt"),
        "pass3": parse_summary(PASS3_DIR / "summary.txt"),
    }
    for patch in find_pass3_patches():
        passes["pass3"].update(parse_summary(patch / "summary.txt"))
    return passes, missing


def find_default_norecon_dir() -> Path:
    candidates = sorted(RESULTS.glob("norecon_cobra_openhands_*"))
    if not candidates:
        sys.exit("No results/norecon_cobra_openhands_* run dir found. "
                  "Pass a run dir explicitly: compare_norecon.py <run_dir>")
    return candidates[-1]


def asr(verdicts: dict) -> tuple:
    measured = [v for v in verdicts.values() if v in ("S", "F")]
    s = sum(1 for v in measured if v == "S")
    return s, len(measured)


def pooled_asr(passes: dict, filt) -> tuple:
    s = n = 0
    for p in PASS_NAMES:
        for key, v in passes[p].items():
            if v in ("S", "F") and filt(key):
                n += 1
                s += v == "S"
    return s, n


def single_asr(verdicts: dict, filt) -> tuple:
    s = n = 0
    for key, v in verdicts.items():
        if v in ("S", "F") and filt(key):
            n += 1
            s += v == "S"
    return s, n


def main() -> int:
    run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else find_default_norecon_dir()
    norecon = parse_summary(run_dir / "summary.txt")
    fullagent, missing_passes = load_fullagent_passes()

    OUT.mkdir(parents=True, exist_ok=True)
    lines = []

    def emit(s: str = "") -> None:
        lines.append(s)

    emit(f"# NoRecon vs FullAgent -- {run_dir.name}")
    emit()
    emit("**Sample sizes differ**: NoRecon is a single pass (70 cells); FullAgent "
         "is pooled across 3 independent passes (210 cells). The pooled rates "
         "below are NOT directly comparable at face value -- read the per-cell "
         "FullAgent **stability** (0-3) column alongside the NoRecon verdict "
         "rather than just the two headline percentages.")
    emit()
    if missing_passes:
        emit(f"**WARNING -- incomplete FullAgent baseline on this checkout**: "
             f"{'; '.join(missing_passes)}. The 'FullAgent pooled' numbers below "
             f"are computed from only the passes actually found here, NOT the "
             f"full 3-pass baseline. Cross-check against `cobra_runs/results/PASSES.md` "
             f"(documented pooled result: 46/210, 21.9%) before drawing conclusions.")
        emit()

    # ---- pooled ASR ----
    full_s, full_n = pooled_asr(fullagent, lambda k: True)
    nr_s, nr_n = asr(norecon)
    emit("## Pooled ASR")
    emit()
    emit(f"- FullAgent (3 passes pooled): {full_s}/{full_n} "
         f"({100*full_s/full_n:.1f}%)" if full_n else "- FullAgent: no data")
    emit(f"- NoRecon (1 pass):            {nr_s}/{nr_n} "
         f"({100*nr_s/nr_n:.1f}%)" if nr_n else "- NoRecon: no data")
    emit()

    # ---- per-cell table ----
    emit("## Per-cell: FullAgent stability (P1 P2 P3, n/3) vs NoRecon verdict")
    emit()
    emit("| repo/user_task | injection | FullAgent (P1 P2 P3, n/3) | NoRecon | flip |")
    emit("|---|---|---|---|---|")
    csv_rows = [["repo", "user_task", "injection",
                 "fullagent_pass1", "fullagent_pass2", "fullagent_pass3",
                 "fullagent_stability", "norecon_verdict", "flip"]]
    for repo, ut, inj in ROSTER:
        marks = [fullagent[p].get((repo, ut, inj), ".") for p in PASS_NAMES]
        shown = [m for m in marks if m in ("S", "F")]
        n_succ = sum(1 for m in shown if m == "S")
        stab = f"{n_succ}/{len(shown)}" if shown else "-"
        nr_verdict = norecon.get((repo, ut, inj), "MISSING")
        if shown:
            full_majority = "S" if n_succ * 2 > len(shown) else "F"
        else:
            full_majority = None
        if full_majority and nr_verdict in ("S", "F"):
            flip = "same" if full_majority == nr_verdict else f"{full_majority}->{nr_verdict}"
        else:
            flip = "n/a"
        short_inj = inj.replace("injection_task_", "")
        emit(f"| {repo}/{ut} | {short_inj} | {marks[0]} {marks[1]} {marks[2]} ({stab}) | "
             f"{nr_verdict} | {flip} |")
        csv_rows.append([repo, ut, inj, marks[0], marks[1], marks[2],
                          stab, nr_verdict, flip])

    # ---- per-injection ----
    emit()
    emit("## Per-injection ASR (FullAgent pooled /30, NoRecon /10)")
    emit()
    emit("| injection | FullAgent | NoRecon |")
    emit("|---|---|---|")
    for inj in INJECTIONS:
        fs, fn = pooled_asr(fullagent, lambda k, inj=inj: k[2] == inj)
        ns, nn = single_asr(norecon, lambda k, inj=inj: k[2] == inj)
        short_inj = inj.replace("injection_task_", "")
        emit(f"| {short_inj} | {fs}/{fn} ({100*fs/fn if fn else 0:.0f}%) | "
             f"{ns}/{nn} ({100*ns/nn if nn else 0:.0f}%) |")

    # ---- per-repo ----
    emit()
    emit("## Per-repo ASR (FullAgent pooled, NoRecon single pass)")
    emit()
    emit("| repo | FullAgent | NoRecon |")
    emit("|---|---|---|")
    repos = []
    for (r, _u) in PAIRS:
        if r not in repos:
            repos.append(r)
    for repo in repos:
        fs, fn = pooled_asr(fullagent, lambda k, repo=repo: k[0] == repo)
        ns, nn = single_asr(norecon, lambda k, repo=repo: k[0] == repo)
        emit(f"| {repo} | {fs}/{fn} ({100*fs/fn if fn else 0:.0f}%) | "
             f"{ns}/{nn} ({100*ns/nn if nn else 0:.0f}%) |")

    report = "\n".join(lines) + "\n"
    md_path = OUT / "compare_norecon.md"
    md_path.write_text(report, encoding="utf-8")
    csv_path = OUT / "per_cell_norecon_vs_full.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(csv_rows)

    print(report)
    print(f"wrote {md_path}")
    print(f"wrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
