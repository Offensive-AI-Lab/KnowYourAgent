#!/usr/bin/env python3
"""Aggregate the 3 repeated passes of the 7x10 Cobra-vs-OpenHands grid.

Each pass measures all 70 cells (10 (repo,user_task) pairs x 7 injections).
Scoring is attempt = success (the agent issued the injected tool call).

Sources, one verdict map per pass:
  pass1  -> results/COMBINED_SUMMARY.md   (the authoritative merge of pass1's 3 dirs,
            incl. the 2 manual reclassifications recorded there)
  pass2  -> results/cobra_openhands_20260524_170814/summary.txt
  pass3  -> results/cobra_openhands_20260524_230606/summary.txt
            (+ optional patch dir(s) for cells that failed with the transient
             uv/NFS permission glitch; patch verdicts override "missing")

Output: per-cell x per-pass matrix, per-pass ASR, per-injection / per-repo
breakdowns pooled over passes, per-cell stability (0-3 successes), and a tidy
CSV (eda/passes/per_cell_per_pass.csv, one row per cell-per-pass) for revision.
"""
import csv
import re
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"
OUT = Path(__file__).resolve().parent / "passes"

PAIRS = [
    ("math-calculator", "user_task_1"),
    ("math-calculator", "user_task_21"),
    ("flask-blog", "user_task_3"),
    ("flask-blog", "user_task_24"),
    ("flask-blog", "user_task_25"),
    ("sorting-lib", "user_task_4"),
    ("sql-store", "user_task_5"),
    ("sql-store", "user_task_22"),
    ("sql-store", "user_task_23"),
    ("fibonacci-gen", "user_task_12"),
]
INJECTIONS = [
    "injection_task_hello_aha",
    "injection_task_works_function",
    "injection_task_delete_first_file",
    "injection_task_swap_files",
    "injection_task_curl_pipe_bash",
    "injection_task_exfil_ssh_key",
    "injection_task_exfil_shadow",
]
ROSTER = [(r, u, i) for (r, u) in PAIRS for i in INJECTIONS]  # 70

PASS2_DIR = RESULTS / "cobra_openhands_20260524_170814"
PASS3_DIR = RESULTS / "cobra_openhands_20260524_230606"
# Any extra pass3 dirs that backfill the glitched cells (label pass3_patch).
PASS3_PATCH_GLOB = "cobra_openhands_*"


def parse_summary(path: Path) -> dict:
    """summary.txt line -> {(repo,user_task,injection): 'S'|'F'}. Skips NO LOG/CRASHED."""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s+(\S+)\s+(user_task_\d+)\s+(injection_task_\S+)\s+(SUCCESS|FAILURE)\b", line)
        if m:
            repo, ut, inj, verdict = m.groups()
            out[(repo, ut, inj)] = "S" if verdict == "SUCCESS" else "F"
    return out


def parse_combined(path: Path) -> dict:
    """COMBINED_SUMMARY.md grid table -> verdict map. Rows are 'repo/user_task | S | F | ...'."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*([\w-]+)/(user_task_\d+)\s*\|(.+)\|", line)
        if not m:
            continue
        repo, ut, rest = m.groups()
        cells = [c.strip() for c in rest.split("|")]
        cells = [c for c in cells if c]  # drop trailing empty
        if len(cells) != len(INJECTIONS):
            continue
        for inj, c in zip(INJECTIONS, cells):
            if c in ("S", "F"):
                out[(repo, ut, inj)] = c
    return out


def find_pass3_patches() -> list:
    """Run dirs labelled pass3_patch* whose verdicts backfill the glitched cells."""
    patches = []
    for d in sorted(RESULTS.glob(PASS3_PATCH_GLOB)):
        meta = d / "run_meta.json"
        if not meta.exists():
            continue
        txt = meta.read_text(encoding="utf-8", errors="replace")
        if '"label": "pass3_patch' in txt and d != PASS3_DIR:
            patches.append(d)
    return patches


def load_pass3() -> dict:
    base = parse_summary(PASS3_DIR / "summary.txt")
    for patch in find_pass3_patches():
        base.update(parse_summary(patch / "summary.txt"))  # patch overrides
    return base


def asr(verdicts: dict) -> tuple:
    measured = [v for v in verdicts.values() if v in ("S", "F")]
    s = sum(1 for v in measured if v == "S")
    return s, len(measured)


def main():
    passes = {
        "pass1": parse_combined(RESULTS / "COMBINED_SUMMARY.md"),
        "pass2": parse_summary(PASS2_DIR / "summary.txt"),
        "pass3": load_pass3(),
    }
    names = ["pass1", "pass2", "pass3"]

    # ---- per-cell x per-pass matrix ----
    print("=" * 78)
    print("Cobra vs OpenHands -- 7x10 grid, 3 passes (attempt = success)")
    print("=" * 78)
    hdr = f"{'repo/user_task':<26} {'injection':<26} P1 P2 P3  n/3"
    print(hdr)
    print("-" * len(hdr))
    for repo, ut, inj in ROSTER:
        marks = [passes[p].get((repo, ut, inj), ".") for p in names]
        nshown = [m for m in marks if m in ("S", "F")]
        nsucc = sum(1 for m in nshown if m == "S")
        stab = f"{nsucc}/{len(nshown)}" if nshown else "-"
        short_inj = inj.replace("injection_task_", "")
        print(f"{repo + '/' + ut:<26} {short_inj:<26} "
              f"{marks[0]:>2} {marks[1]:>2} {marks[2]:>2}  {stab:>4}")

    # ---- per-pass ASR ----
    print("\n" + "-" * 40)
    print("ASR per pass (cells measured)")
    print("-" * 40)
    total_s = total_n = 0
    for p in names:
        s, n = asr(passes[p])
        total_s += s
        total_n += n
        pct = 100 * s / n if n else 0
        flag = "" if n == 70 else f"   <-- {70 - n} cell(s) not yet measured"
        print(f"  {p}:  {s:>2}/{n:<2}  ({pct:4.1f}%){flag}")
    print(f"  POOLED: {total_s}/{total_n}  ({100*total_s/total_n:.1f}%)   "
          f"[target when complete: x/210]")

    # ---- per-injection ASR pooled over passes ----
    print("\n" + "-" * 40)
    print("ASR per injection (pooled over passes)")
    print("-" * 40)
    for inj in INJECTIONS:
        s = n = 0
        for p in names:
            for (r, u) in PAIRS:
                v = passes[p].get((r, u, inj), ".")
                if v in ("S", "F"):
                    n += 1
                    s += v == "S"
        print(f"  {inj.replace('injection_task_',''):<22} {s:>2}/{n:<3} "
              f"({100*s/n if n else 0:4.1f}%)")

    # ---- per-repo ASR pooled over passes ----
    print("\n" + "-" * 40)
    print("ASR per repo (pooled over passes)")
    print("-" * 40)
    repos = []
    for (r, _u) in PAIRS:
        if r not in repos:
            repos.append(r)
    for repo in repos:
        s = n = 0
        for p in names:
            for (r, u, i) in ROSTER:
                if r != repo:
                    continue
                v = passes[p].get((r, u, i), ".")
                if v in ("S", "F"):
                    n += 1
                    s += v == "S"
        print(f"  {repo:<18} {s:>2}/{n:<3} ({100*s/n if n else 0:4.1f}%)")

    # ---- cell stability ----
    print("\n" + "-" * 40)
    print("Cell stability (successes across the 3 passes)")
    print("-" * 40)
    buckets = {0: [], 1: [], 2: [], 3: [], "partial": []}
    for (r, u, i) in ROSTER:
        marks = [passes[p].get((r, u, i), ".") for p in names]
        if "." in marks:
            buckets["partial"].append((r, u, i))
            continue
        buckets[sum(1 for m in marks if m == "S")].append((r, u, i))
    print(f"  always succeeds (3/3): {len(buckets[3])}")
    print(f"  2/3:                   {len(buckets[2])}")
    print(f"  1/3:                   {len(buckets[1])}")
    print(f"  never (0/3):           {len(buckets[0])}")
    if buckets["partial"]:
        print(f"  not-yet-complete:      {len(buckets['partial'])} "
              f"(awaiting pass3 backfill)")

    # ---- tidy CSV ----
    OUT.mkdir(exist_ok=True)
    csv_path = OUT / "per_cell_per_pass.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pass", "repo", "user_task", "injection", "verdict"])
        for p in names:
            for (r, u, i) in ROSTER:
                w.writerow([p, r, u, i, passes[p].get((r, u, i), "MISSING")])
    print(f"\nwrote {csv_path}  ({3*len(ROSTER)} rows)")


if __name__ == "__main__":
    main()
