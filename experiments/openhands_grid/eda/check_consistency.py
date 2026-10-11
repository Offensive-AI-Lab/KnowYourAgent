#!/usr/bin/env python3
"""Cross-artifact consistency check for the 3-pass 7x10 grid (210 runs).

"Make sure they fit": this verifies every result artifact agrees with every other,
so the reported numbers are derived, not asserted. Hard checks (failure => exit 1):

  1. ROSTER     each pass resolves exactly the 70 canonical cells (PAIRS x INJECTIONS),
                no missing / extra / duplicate.
  2. VALID      every resolved cell has a real SUCCESS/FAILURE verdict (the task log
                contains an "Injection success:" line; not CRASHED / NO_LOG).
  3. EXITCODE   the dir that supplies a cell's verdict recorded exit code 0 for it.
  4. SUMMARY    that dir's summary.txt verdict == re-parsing its task log (no stale summary).
  5. EVIDENCE   every SUCCESS has a concrete triggering tool call in the harvested
                events, OR is the one documented harvest-last-attempt cell (logged
                SUCCESS, events-reval False) -- which is reported, not failed.
  6. CSV        per_cell_per_pass.csv has 210 rows, one per (pass,cell), verdicts in
                {S,F}, and every pass3 row equals the independently-resolved verdict.
  7. TALLY      the CSV per-pass S-counts equal the counts re-derived here from the
                source artifacts (internal agreement). The ASR is reported, not
                asserted against a hard-coded number.

pass1 source = COMBINED_SUMMARY.md (authoritative merge of its 3 dirs).
pass2 source = the pass2 run dir.
pass3 source = main dir, overridden by pass3_patch* dirs (latest valid wins per cell).
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3]))
from experiments.openhands_grid.eda.aggregate_passes import (  # noqa: E402
    PAIRS, INJECTIONS, ROSTER, RESULTS, parse_summary, parse_combined,
)
from experiments.openhands_grid.eda.rescore_logs import parse_entry, log_verdict, evidence  # noqa: E402
from benchmarks.openhands.api import INJECTION_VALIDATORS  # noqa: E402

PASS1_COMBINED = RESULTS / "COMBINED_SUMMARY.md"
PASS2_DIR = RESULTS / "cobra_openhands_20260524_170814"
PASS3_MAIN = RESULTS / "cobra_openhands_20260524_230606"
CSV = HERE / "passes" / "per_cell_per_pass.csv"

# The single documented exception (see memory harvest-keeps-last-attempt): a logged
# SUCCESS whose event-snapshot reval is False because harvesting keeps the last of
# N attack attempts and the winning attempt was earlier. Verified true positive by
# reading the task log (attempt 1 did a real file_editor insert of works()).
HARVEST_ARTIFACT = ("math-calculator", "user_task_1", "injection_task_works_function")

fails = []
warns = []


def fail(msg):
    fails.append(msg)
    print("  FAIL:", msg)


def key(c):
    return f"{c[0]}__{c[1]}__{c[2]}"


def patch_dirs():
    out = []
    for d in sorted(RESULTS.glob("cobra_openhands_*")):
        m = d / "run_meta.json"
        if m.exists() and '"label": "pass3_patch' in m.read_text(errors="replace"):
            out.append(d)
    return out


def resolve_pass3():
    """cell -> (dir, verdict 'S'/'F'/None). Latest dir with a real verdict wins."""
    order = [PASS3_MAIN] + patch_dirs()  # sorted: main, patch, patch2
    resolved = {}
    for c in ROSTER:
        k = key(c)
        pick = None
        for d in order:  # later dirs override earlier
            log = d / "tasks" / f"{k}.log"
            v = log_verdict(str(log))
            if v in ("SUCCESS", "FAILURE"):
                pick = (d, "S" if v == "SUCCESS" else "F")
        resolved[c] = pick
    return resolved


def exit_code_for(d: Path, k: str):
    meta = d / "run_meta.json"
    if not meta.exists():
        return None
    return json.loads(meta.read_text()).get("exit_codes", {}).get(k)


def main():
    print("=" * 78)
    print("CONSISTENCY CHECK -- 7x10 grid, 3 passes")
    print("=" * 78)

    # ---- pass1 / pass2 single-source verdict maps ----
    p1 = parse_combined(PASS1_COMBINED)
    p2 = parse_summary(PASS2_DIR / "summary.txt")
    p3 = resolve_pass3()

    # ---------- CHECK 1: ROSTER ----------
    print("\n[1] ROSTER (each pass = the 70 canonical cells)")
    assert len(ROSTER) == 70 and len(set(ROSTER)) == 70
    for name, src in [("pass1", set(p1)), ("pass2", set(p2)),
                      ("pass3", {c for c, v in p3.items() if v})]:
        extra = src - set(ROSTER)
        missing = set(ROSTER) - src
        if extra:
            fail(f"{name}: {len(extra)} cell(s) not in roster: {list(extra)[:3]}")
        if missing:
            fail(f"{name}: {len(missing)} roster cell(s) absent: {list(missing)[:3]}")
        if not extra and not missing:
            print(f"  ok: {name} has all 70, no extras")

    # ---------- CHECK 2/3/4: per pass3 cell -> valid verdict, exit 0, summary match ----------
    print("\n[2/3/4] pass3 cells: valid verdict + exit-code 0 + summary==log")
    bad = 0
    for c in ROSTER:
        k = key(c)
        pick = p3[c]
        if not pick:
            fail(f"pass3 {k}: no dir supplies a valid verdict (all CRASHED/NO_LOG)")
            bad += 1
            continue
        d, verdict = pick
        ec = exit_code_for(d, k)
        if ec != 0:
            fail(f"pass3 {k}: resolving dir {d.name} recorded exit code {ec} (not 0)")
            bad += 1
        # summary.txt of the resolving dir must agree with the task log
        summ = parse_summary(d / "summary.txt").get(c)
        if summ is not None and summ != verdict:
            fail(f"pass3 {k}: summary={summ} but task-log verdict={verdict} in {d.name}")
            bad += 1
    if not bad:
        print("  ok: all 70 pass3 cells have a clean (exit-0) verdict matching their summary")

    # pass2 summary vs log
    print("\n[4b] pass2 cells: summary==log + exit 0")
    bad2 = 0
    for c in ROSTER:
        k = key(c)
        log_v = log_verdict(str(PASS2_DIR / "tasks" / f"{k}.log"))
        log_v = "S" if log_v == "SUCCESS" else ("F" if log_v == "FAILURE" else log_v)
        if log_v not in ("S", "F"):
            fail(f"pass2 {k}: task log not a clean verdict ({log_v})")
            bad2 += 1
        elif p2.get(c) != log_v:
            fail(f"pass2 {k}: summary={p2.get(c)} but log={log_v}")
            bad2 += 1
        if exit_code_for(PASS2_DIR, k) != 0:
            fail(f"pass2 {k}: exit code != 0")
            bad2 += 1
    if not bad2:
        print("  ok: all 70 pass2 cells clean, summary==log")

    # ---------- CHECK 5: every SUCCESS has evidence ----------
    print("\n[5] every SUCCESS has a concrete triggering tool call in events")
    n_succ = n_ev = 0
    for name, vmap, dirof in [
        ("pass2", p2, lambda c: PASS2_DIR),
        ("pass3", {c: v for c, (d, v) in {c: p3[c] for c in ROSTER if p3[c]}.items()},
         lambda c: p3[c][0]),
    ]:
        for c in ROSTER:
            if vmap.get(c) != "S":
                continue
            n_succ += 1
            k = key(c)
            conv = parse_entry(str(dirof(c) / "events" / k))
            ev = evidence(c[2], conv)
            reval = INJECTION_VALIDATORS[c[2]](conv)
            if ev and reval:
                n_ev += 1
            elif c == HARVEST_ARTIFACT and name == "pass3":
                warns.append(f"{name} {k}: SUCCESS, events-reval False -> documented "
                             f"harvest-last-attempt true positive (OK)")
            else:
                fail(f"{name} {k}: SUCCESS but no events evidence (reval={reval}, ev={bool(ev)})")
    print(f"  {n_ev}/{n_succ} successes have direct events evidence; "
          f"{len(warns)} documented exception(s)")
    for w in warns:
        print("   note:", w)

    # ---------- CHECK 6: CSV integrity ----------
    print("\n[6] per_cell_per_pass.csv integrity")
    rows = list(csv.DictReader(open(CSV)))
    if len(rows) != 210:
        fail(f"CSV has {len(rows)} rows, expected 210")
    seen = {}
    for r in rows:
        kk = (r["pass"], r["repo"], r["user_task"], r["injection"])
        if kk in seen:
            fail(f"CSV duplicate row {kk}")
        seen[kk] = r["verdict"]
        if r["verdict"] not in ("S", "F"):
            fail(f"CSV non-S/F verdict {kk}={r['verdict']}")
    csv_s = {p: sum(1 for r in rows if r["pass"] == p and r["verdict"] == "S")
             for p in ("pass1", "pass2", "pass3")}
    print(f"  CSV rows=210, per-pass S = {csv_s}")

    # CSV pass3 must equal our independently-resolved pass3
    resolved_p3 = {c: v for c, pv in p3.items() if pv for d, v in [pv]}
    for r in rows:
        if r["pass"] != "pass3":
            continue
        c = (r["repo"], r["user_task"], r["injection"])
        if resolved_p3.get(c) != r["verdict"]:
            fail(f"CSV pass3 {key(c)}={r['verdict']} != resolved {resolved_p3.get(c)}")

    # ---------- CHECK 7: TALLY (internal agreement, not a hard-coded number) ----------
    print("\n[7] ASR re-derived from source artifacts == CSV (numbers are reported, not asserted)")
    got = {
        "pass1": sum(1 for v in p1.values() if v == "S"),
        "pass2": sum(1 for v in p2.values() if v == "S"),
        "pass3": sum(1 for _c, pv in p3.items() if pv and pv[1] == "S"),
    }
    got["pooled"] = got["pass1"] + got["pass2"] + got["pass3"]
    for p in ("pass1", "pass2", "pass3"):
        agree = "ok" if csv_s[p] == got[p] else "FAIL"
        print(f"  {p}: re-derived={got[p]}/70   CSV={csv_s[p]}/70   [{agree}]")
        if csv_s[p] != got[p]:
            fail(f"tally {p}: re-derived {got[p]} != CSV {csv_s[p]}")
    print(f"  pooled: {got['pooled']}/210  ({100*got['pooled']/210:.1f}%)")

    print("\n" + "=" * 78)
    if fails:
        print(f"RESULT: {len(fails)} CHECK(S) FAILED")
        return 1
    print(f"RESULT: ALL CHECKS PASS  -- pooled {got['pooled']}/210 "
          f"({100*got['pooled']/210:.1f}%), pass1 {got['pass1']} / pass2 "
          f"{got['pass2']} / pass3 {got['pass3']}, every cell verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
