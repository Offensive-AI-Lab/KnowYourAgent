"""Build unified per-attempt parquet across the 8 attack frameworks.

Output:
  Data/EDA/parquet/per_attempt.parquet   — one row per (framework, suite, UT, IJ, defense, knowledge_set, attempt)
  Data/EDA/parquet/asr_per_cell.parquet  — groupby aggregate
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

import os
HERE = Path(__file__).resolve().parent
# Raw per-attempt logs are NOT shipped (see README). Point these at your own
# run outputs to rebuild the parquet; the shipped parquet/ already holds the result.
ROOT = Path(os.environ.get("KYA_RAW_DATA_ROOT", HERE / "raw_data"))
EXP = ROOT / "Experiments"
OUT = HERE / "parquet"
OUT.mkdir(parents=True, exist_ok=True)

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
SECURITY_LINE = re.compile(r"^Security \(attack success\):\s*(True|False)", re.MULTILINE)
UTILITY_LINE = re.compile(r"^Utility:\s*(True|False)", re.MULTILINE)
EVALUATOR_SUCCESS = re.compile(r'"failure_type"\s*:\s*"SUCCESS"')
EVALUATOR_FAIL = re.compile(r'"failure_type"\s*:\s*"(STRATEGY_\w+_FAILURE|GUARDRAILS_FAILURE)"')
PROG_SUCCESS = re.compile(r"Attack succeeded")
EVALUATOR_HEADER = re.compile(r"# Agent:.*?Evaluator", re.IGNORECASE)
EXEC_ATTACK_HEADER = re.compile(r"# Agent: Execute the attack", re.IGNORECASE)
PAYLOAD_BLOCK = re.compile(
    r"# Agent: Execute the attack\s*## Final Answer:\s*(\{.*?\})\s*(?=\n\n|\Z|\#)",
    re.DOTALL,
)


def canon_model(s: str | None) -> str | None:
    if s is None:
        return None
    s = s.replace(" ", "")
    table = {
        "gpt-4-1": "gpt-4.1",
        "gpt-4.1": "gpt-4.1",
        "gpt-4-1-2025-04-14": "gpt-4.1",
        "gpt-4.1-2025-04-14": "gpt-4.1",
        "gpt-4o-2024-05-13": "gpt-4o",
        "gpt-4o-mini-2024-07-18": "gpt-4o-mini",
        "gpt-4o-mini": "gpt-4o-mini",
        "gpt-4o": "gpt-4o",
    }
    return table.get(s, s)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def parse_cobra_ans(path: Path) -> list[dict]:
    """Return a list of attempt rows. For files lacking explicit attempts,
    return one row with attempt_idx=0."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    content = strip_ansi(raw)

    # Security signal: prefer V3/V4 explicit lines; fall back to Evaluator JSON.
    sec_matches = SECURITY_LINE.findall(content)
    util_matches = UTILITY_LINE.findall(content)
    prog_skip = bool(PROG_SUCCESS.search(content))
    eval_succ = bool(EVALUATOR_SUCCESS.search(content))

    # Per-attempt evaluator JSON blocks (V1/V2/V3 all use them)
    eval_blocks = re.findall(
        r'```json\s*(\{[^`]+?\})\s*```',
        content,
    )
    parsed_evals = []
    for block in eval_blocks:
        try:
            d = json.loads(block)
            ft = d.get("failure_type")
            if ft is not None:
                parsed_evals.append(ft)
        except Exception:
            pass

    # Extract payload(s) from "Execute the attack" final answers.
    payloads = []
    for m in PAYLOAD_BLOCK.finditer(content):
        try:
            d = json.loads(m.group(1))
            if "content" in d:
                payloads.append(d["content"])
            else:
                payloads.append(m.group(1))
        except Exception:
            payloads.append(m.group(1)[:1000])

    # Decide overall security.
    security = None
    if sec_matches:
        security = sec_matches[-1] == "True"
    elif eval_succ or prog_skip:
        security = True
    elif parsed_evals:
        # Any SUCCESS in any attempt => success.
        security = any(ft == "SUCCESS" for ft in parsed_evals)

    utility = None
    if util_matches:
        utility = util_matches[-1] == "True"

    n_attempts = max(len(parsed_evals), 1)

    rows = []
    for i, ft in enumerate(parsed_evals or [None]):
        row_security = security if i == n_attempts - 1 else (ft == "SUCCESS" if ft else None)
        rows.append({
            "attempt_idx": i + 1,
            "evaluator_label": ft,
            "security": row_security,
            "utility": utility if i == n_attempts - 1 else None,
            "payload": payloads[i] if i < len(payloads) else (payloads[-1] if payloads else None),
        })
    # If we found zero eval blocks but have a security signal, emit one row.
    if not rows:
        rows = [{
            "attempt_idx": 0,
            "evaluator_label": None,
            "security": security,
            "utility": utility,
            "payload": payloads[0] if payloads else None,
        }]
    return rows


def parse_filename_ut_ij(path: Path) -> tuple[int | None, int | None]:
    """Extract user_task and injection_task ids from filename.
    Patterns: ut_3.ans, ut_3_ij_0.ans, ut_3.ans"""
    name = path.stem
    m_ut = re.search(r"ut[_\-]?(\d+)", name, re.IGNORECASE)
    m_ij = re.search(r"ij[_\-]?(\d+)", name, re.IGNORECASE)
    return (int(m_ut.group(1)) if m_ut else None,
            int(m_ij.group(1)) if m_ij else None)


# ---------------------------------------------------------------------------
# Per-framework ingesters
# ---------------------------------------------------------------------------

def ingest_asr_knowledge() -> list[dict]:
    rows = []
    base = EXP / "ASR-Knowledge"
    if not base.exists():
        return rows
    for results_path in base.rglob("results.json"):
        # path: ASR-Knowledge/{suite}/{asset}/{defense}/[irrelevant/]results.json
        parts = results_path.relative_to(base).parts
        if len(parts) < 4:
            continue
        suite = parts[0]
        asset = parts[1]
        defense = parts[2]
        relevance = "irrelevant" if "irrelevant" in parts else "relevant"
        try:
            d = json.loads(results_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for key, rec in d.get("results", {}).items():
            # key like "banking/injection_task_0/user_task_5"
            m = re.match(r"([\w]+)/injection_task_(\d+)/user_task_(\d+)", key)
            if not m:
                continue
            suite_in_key, ij_id, ut_id = m.group(1), int(m.group(2)), int(m.group(3))
            messages = rec.get("messages") or []
            rows.append({
                "framework": "asr_knowledge",
                "cobra_variant": None,
                "model": "gpt-4.1",  # ASR-Knowledge canonically uses gpt-4.1
                "defense": defense,
                "knowledge_set": asset,
                "relevance": relevance,
                "suite": suite,
                "user_task_id": ut_id,
                "injection_task_id": ij_id,
                "attempt_idx": 0,
                "security": bool(rec.get("security")) if rec.get("security") is not None else None,
                "utility": bool(rec.get("utility")) if rec.get("utility") is not None else None,
                "error": None,
                "payload": rec.get("payload"),
                "payload_len": len(rec.get("payload") or ""),
                "duration_s": None,
                "n_msg_turns": len(messages) if isinstance(messages, list) else None,
                "raw_path": str(results_path),
            })
    return rows


def _cobra_iter_files(base: Path, framework: str) -> list[tuple[Path, dict]]:
    """Yield (path, context dict with suite/ij/cobra_variant/model/defense)."""
    out = []
    for ans in base.rglob("*.ans"):
        rel = ans.relative_to(base).parts
        # Skip __pycache__ or other oddities
        if any(p.startswith(".") for p in rel):
            continue
        ctx = {
            "framework": framework,
            "cobra_variant": None,
            "model": None,
            "defense": "none",
        }
        # Determine semantics from path structure
        parts = list(rel)
        # known config tokens
        config_map = {
            "AgentDojo": ("agentdojo", "none"),
            "AgentDojoRepeatPrompt": ("agentdojo", "repeat_user_prompt"),
            "AgentDojoDelimiters": ("agentdojo", "spotlighting_with_delimiting"),
            "AgentDojoNoTactics": ("agentdojo", "none"),  # NoTactics is an ablation
            "AgentDojoNoRecon": ("agentdojo", "none"),    # NoRecon is an ablation
            "InjecAgent": ("injecagent", "none"),
            "Standard": (None, None),
            "Enhanced": (None, None),
            "FullAgent": (None, None),
            "NoRecon": (None, None),
        }
        for p in parts:
            if p in {"gpt-4-1", "gpt-4-1-2025-04-14"}:
                ctx["model"] = "gpt-4.1"
            elif p == "gpt-4o-2024-05-13":
                ctx["model"] = "gpt-4o"
            elif p in {"AgentDojoRepeatPrompt"}:
                ctx["defense"] = "repeat_user_prompt"
            elif p == "AgentDojoDelimiters":
                ctx["defense"] = "spotlighting_with_delimiting"
            elif p == "AgentDojoNoRecon":
                ctx["cobra_variant"] = "NoRecon"
            elif p == "AgentDojoNoTactics":
                ctx["cobra_variant"] = "NoTactics"
            elif p == "Standard":
                if ctx["cobra_variant"] is None:
                    ctx["cobra_variant"] = "Standard"
            elif p == "Enhanced":
                if ctx["cobra_variant"] is None:
                    ctx["cobra_variant"] = "Enhanced"
            elif p == "FullAgent":
                if ctx["cobra_variant"] is None:
                    ctx["cobra_variant"] = "FullAgent"
                elif ctx["cobra_variant"] in {"Standard", "Enhanced"}:
                    ctx["cobra_variant"] = ctx["cobra_variant"] + "+FullAgent"
            elif p == "NoRecon":
                if ctx["cobra_variant"] is None:
                    ctx["cobra_variant"] = "NoRecon"
                else:
                    ctx["cobra_variant"] = ctx["cobra_variant"] + "+NoRecon"

        # Suite: look for known suite names
        for p in parts:
            if p in {"banking", "slack", "travel", "workspace", "dh", "ds"}:
                ctx["suite"] = p
                break
        else:
            ctx["suite"] = None
        out.append((ans, ctx))
    return out


def ingest_cobra(version: int) -> list[dict]:
    base = EXP / f"CobraV{version}"
    if not base.exists():
        return []
    framework = f"cobra_v{version}"
    rows = []
    files = _cobra_iter_files(base, framework)
    for path, ctx in files:
        ut_id, ij_id_filename = parse_filename_ut_ij(path)
        # injection_task_id usually comes from parent dir "ij{N}"
        parent_ij = re.search(r"ij(\d+)", path.parent.name)
        ij_id = int(parent_ij.group(1)) if parent_ij else ij_id_filename
        parsed = parse_cobra_ans(path)
        for r in parsed:
            payload = r.get("payload")
            rows.append({
                "framework": framework,
                "cobra_variant": ctx.get("cobra_variant"),
                "model": canon_model(ctx.get("model")),
                "defense": ctx.get("defense", "none"),
                "knowledge_set": None,
                "relevance": None,
                "suite": ctx.get("suite"),
                "user_task_id": ut_id,
                "injection_task_id": ij_id,
                "attempt_idx": r["attempt_idx"],
                "security": r["security"],
                "utility": r["utility"],
                "error": None,
                "payload": payload,
                "payload_len": len(payload) if payload else 0,
                "duration_s": None,
                "n_msg_turns": None,
                "raw_path": str(path),
                "evaluator_label": r.get("evaluator_label"),
            })
    return rows


_TOPIC_SUITES = {"banking", "slack", "travel", "workspace"}


def _topicattack_classify(txt: Path, base: Path) -> tuple[str | None, str, str] | None:
    """Return (suite, model, defense) for a TopicAttack .txt path, or None."""
    rel = txt.relative_to(base).parts
    stem = txt.stem
    # Suite: stem might be "banking", "banking_ij0", "banking0", etc.
    suite = None
    for s in _TOPIC_SUITES:
        if stem.startswith(s):
            suite = s
            break
    if suite is None:
        return None
    model = canon_model(rel[0]) or rel[0]
    defense = "none"
    if len(rel) >= 3:
        tok = rel[1].lower()
        if "pi-detector" in tok or "pi_detector" in tok:
            defense = "transformers_pi_detector"
        elif "repeat-prompt" in tok or "repeat_prompt" in tok:
            defense = "repeat_user_prompt"
        elif "delimiter" in tok:
            defense = "spotlighting_with_delimiting"
        elif tok == rel[0].lower() or tok == "agentdojo":
            defense = "none"
        else:
            defense = "none"
    return suite, model, defense


def ingest_topicattack() -> list[dict]:
    base = EXP / "TopicAttack"
    if not base.exists():
        return []
    rows = []
    for txt in base.rglob("*.txt"):
        if " copy" in str(txt):  # skip duplicate dirs
            continue
        info = _topicattack_classify(txt, base)
        if info is None:
            continue
        suite, model, defense = info
        try:
            content = txt.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        # Strip timestamps like "[22:13:31] "
        clean = re.sub(r"\[\d{2}:\d{2}:\d{2}\]\s*", "", content)
        # Split into entry blocks: each starts with "Entry X/Y" (or maybe "Entry X")
        entry_pattern = re.compile(r"Entry\s+\d+(?:/\d+)?\s*\n(.*?)(?=Entry\s+\d+(?:/\d+)?|$)", re.DOTALL)
        for match in entry_pattern.finditer(clean):
            block = match.group(1)
            pair_m = re.search(r"task\s*pair\s*:\s*user_task_(\d+)\s*:\s*injection_task_(\d+)", block)
            # Some variants use different separators
            if not pair_m:
                ut_m = re.search(r"user_task[\s_:=]+(\d+)", block)
                ij_m = re.search(r"injection_task[\s_:=]+(\d+)", block)
                ut_id = int(ut_m.group(1)) if ut_m else None
                ij_id = int(ij_m.group(1)) if ij_m else None
            else:
                ut_id = int(pair_m.group(1))
                ij_id = int(pair_m.group(2))
            sec_m = re.search(r"security\s*\(attack\s*succeeded\)\s*:\s*(True|False)", block, re.IGNORECASE)
            util_m = re.search(r"utility\s*\(task\s*completed\)\s*:\s*(True|False)", block, re.IGNORECASE)
            if sec_m is None and util_m is None and ut_id is None:
                continue
            rows.append({
                "framework": "topicattack",
                "cobra_variant": None,
                "model": model,
                "defense": defense,
                "knowledge_set": None,
                "relevance": None,
                "suite": suite,
                "user_task_id": ut_id,
                "injection_task_id": ij_id,
                "attempt_idx": 0,
                "security": (sec_m.group(1) == "True") if sec_m else None,
                "utility": (util_m.group(1) == "True") if util_m else None,
                "error": None,
                "payload": None,
                "payload_len": 0,
                "duration_s": None,
                "n_msg_turns": None,
                "raw_path": str(txt),
            })
    return rows


def ingest_ignorprev() -> list[dict]:
    base = EXP / "IgnorPrev"
    if not base.exists():
        return []
    rows = []
    for js in base.rglob("injection_task_*.json"):
        try:
            d = json.loads(js.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        m_ij = re.search(r"injection_task_(\d+)\.json", js.name)
        m_ut = re.search(r"user_task_(\d+)", str(js))
        suite = d.get("suite_name")
        pipeline = d.get("pipeline_name") or ""
        defense = "none"
        if "repeat_user_prompt" in pipeline:
            defense = "repeat_user_prompt"
        elif "pi_detector" in pipeline:
            defense = "transformers_pi_detector"
        elif "delimit" in pipeline:
            defense = "spotlighting_with_delimiting"
        # Extract model
        model = None
        m_mod = re.match(r"(gpt[\w\-\.]+?)(-(repeat_user_prompt|transformers_pi_detector|spotlighting.*))?$",
                         pipeline)
        if m_mod:
            model = canon_model(m_mod.group(1))
        inj = d.get("injections") or {}
        # Use the first injection's value as the payload
        payload = next(iter(inj.values()), None) if isinstance(inj, dict) else None
        messages = d.get("messages") or []
        rows.append({
            "framework": "ignorprev",
            "cobra_variant": None,
            "model": model,
            "defense": defense,
            "knowledge_set": None,
            "relevance": None,
            "suite": suite,
            "user_task_id": int(m_ut.group(1)) if m_ut else None,
            "injection_task_id": int(m_ij.group(1)) if m_ij else None,
            "attempt_idx": 0,
            "security": bool(d.get("security")) if d.get("security") is not None else None,
            "utility": bool(d.get("utility")) if d.get("utility") is not None else None,
            "error": d.get("error"),
            "payload": payload,
            "payload_len": len(payload) if payload else 0,
            "duration_s": d.get("duration"),
            "n_msg_turns": len(messages) if isinstance(messages, list) else None,
            "raw_path": str(js),
        })
    return rows


def ingest_agentvigil() -> list[dict]:
    """AgentVigil = the May-12-2026 retrain run, scored on its held-out test
    split only. The retrain MCTS learns attack templates on a 121-case
    fuzzing split, then evaluates them on the remaining held-out cases. Only
    the test split is comparable to the other single-shot baselines, so the
    fuzzing split is excluded.

    The no-defense test-set per-case file was not retained; only the summary
    in retrain/combined_results.json survives. We reconstruct per-suite test
    counts exactly as (combined.by_suite - fuzzing.by_suite) and emit one row
    per case. Identities (user_task_id) are synthetic running indices since
    every figure aggregates AgentVigil by suite, never by (UT, IJ)."""
    retrain = EXP / "agentvigil" / "May-12-2026" / "retrain"
    combined_p = retrain / "combined_results.json"
    fuzzing_p = retrain / "fuzzing_results.json"
    if not combined_p.exists() or not fuzzing_p.exists():
        return []
    combined = json.loads(combined_p.read_text(encoding="utf-8"))
    fuzzing = json.loads(fuzzing_p.read_text(encoding="utf-8"))
    comb_by_suite = combined.get("by_suite", {})   # fuzzing + test, per suite
    fuzz_by_suite = fuzzing.get("by_suite", {})    # fuzzing split only

    rows = []
    for suite, comb in comb_by_suite.items():
        fz = fuzz_by_suite.get(suite, {"unique_cases": 0, "cases_attacked": 0})
        n_test = comb["unique_cases"] - fz["unique_cases"]
        k_test = comb["cases_attacked"] - fz["cases_attacked"]
        for i in range(n_test):
            rows.append({
                "framework": "agentvigil",
                "cobra_variant": None,
                "model": "gpt-4.1",
                "defense": "none",
                "knowledge_set": None,
                "relevance": None,
                "suite": suite,
                "user_task_id": i,
                "injection_task_id": 0,
                "attempt_idx": 0,
                "security": i < k_test,
                "utility": None,
                "error": None,
                "payload": None,
                "payload_len": 0,
                "duration_s": None,
                "n_msg_turns": None,
                "raw_path": str(combined_p),
            })
    return rows


def ingest_chatinject() -> list[dict]:
    base = Path(os.environ.get("KYA_CHATINJECT_LOGS", HERE / "raw_data" / "chatinject_logs"))
    if not base.exists():
        return []
    rows = []
    for js in base.rglob("*.json"):
        # Skip the messages dumps (they are lists of dialogue turns).
        if js.name.endswith(".messages.json"):
            continue
        # path: chatinject_logs/{full|full_<defense>}/{suite}/<file>.json
        rel = js.relative_to(base).parts
        if len(rel) < 3:
            continue
        condition = rel[0]
        suite = rel[1]
        if suite not in {"banking", "slack", "travel", "workspace"}:
            continue
        defense = "none"
        if condition.startswith("full_"):
            d_tok = condition[len("full_"):]
            if d_tok == "transformers_pi_detector":
                defense = "transformers_pi_detector"
            elif d_tok == "repeat_user_prompt":
                defense = "repeat_user_prompt"
            elif d_tok == "spotlighting_with_delimiting":
                defense = "spotlighting_with_delimiting"
            else:
                defense = d_tok
        try:
            d = json.loads(js.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        ut = d.get("user_task_id")
        ij = d.get("injection_task_id")
        m_ut = re.search(r"(\d+)", str(ut or ""))
        m_ij = re.search(r"(\d+)", str(ij or ""))
        status = d.get("status", "ok")
        rows.append({
            "framework": "chatinject",
            "cobra_variant": None,
            "model": canon_model(d.get("model")),
            "defense": defense,
            "knowledge_set": None,
            "relevance": None,
            "suite": suite,
            "user_task_id": int(m_ut.group(1)) if m_ut else None,
            "injection_task_id": int(m_ij.group(1)) if m_ij else None,
            "attempt_idx": 0,
            "security": bool(d.get("security")) if d.get("security") is not None and status == "ok" else None,
            "utility": bool(d.get("utility")) if d.get("utility") is not None and status == "ok" else None,
            "error": d.get("error") if status != "ok" else None,
            "payload": None,  # chatinject payload is a full Qwen3 dialogue; skip body
            "payload_len": d.get("payload_len") or 0,
            "duration_s": d.get("duration_s"),
            "n_msg_turns": None,
            "raw_path": str(js),
        })
    return rows


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build() -> pd.DataFrame:
    all_rows: list[dict] = []
    print("[ingest] asr_knowledge ...", flush=True)
    all_rows += ingest_asr_knowledge()
    print(f"  + asr_knowledge: {len(all_rows)} rows so far")
    for v in (1, 2, 3, 4):
        print(f"[ingest] cobra_v{v} ...", flush=True)
        prev = len(all_rows)
        all_rows += ingest_cobra(v)
        print(f"  + cobra_v{v}: {len(all_rows) - prev}")
    print("[ingest] topicattack ...", flush=True)
    prev = len(all_rows); all_rows += ingest_topicattack(); print(f"  + topicattack: {len(all_rows) - prev}")
    print("[ingest] ignorprev ...", flush=True)
    prev = len(all_rows); all_rows += ingest_ignorprev(); print(f"  + ignorprev: {len(all_rows) - prev}")
    print("[ingest] agentvigil ...", flush=True)
    prev = len(all_rows); all_rows += ingest_agentvigil(); print(f"  + agentvigil: {len(all_rows) - prev}")
    print("[ingest] chatinject ...", flush=True)
    prev = len(all_rows); all_rows += ingest_chatinject(); print(f"  + chatinject: {len(all_rows) - prev}")

    df = pd.DataFrame(all_rows)
    return df


def write(df: pd.DataFrame) -> None:
    out = OUT / "per_attempt.parquet"
    df.to_parquet(out, index=False)
    print(f"[ok] wrote {out} (rows={len(df)})", flush=True)

    # Cell-level aggregate
    keys = ["framework", "cobra_variant", "model", "defense", "knowledge_set",
            "relevance", "suite"]
    keys = [k for k in keys if k in df.columns]
    valid = df[df["security"].notna()].copy()
    cells = valid.groupby(keys, dropna=False).agg(
        n=("security", "size"),
        asr=("security", "mean"),
        n_breached=("security", "sum"),
        utility_rate=("utility", "mean"),
    ).reset_index()
    cells.to_parquet(OUT / "asr_per_cell.parquet", index=False)
    print(f"[ok] wrote {OUT / 'asr_per_cell.parquet'} (cells={len(cells)})")


def main():
    df = build()
    print("\n[summary] row counts by framework:")
    print(df.groupby("framework").size().to_string())
    print("\n[summary] row counts by (framework, suite):")
    print(df.groupby(["framework", "suite"]).size().to_string())
    print("\n[summary] non-null security counts by framework:")
    print(df.groupby("framework")["security"].apply(lambda s: s.notna().sum()).to_string())

    # Spot check the ASR-Knowledge banking/no_knowledge/no_defense cell
    sub = df[(df["framework"] == "asr_knowledge")
             & (df["suite"] == "banking")
             & (df["knowledge_set"] == "no_knowledge")
             & (df["defense"] == "no_defense")]
    if len(sub) > 0:
        asr = sub["security"].mean()
        print(f"\n[sanity] asr_knowledge/banking/no_knowledge/no_defense ASR = "
              f"{asr:.4f} (expected ~0.2986, n={len(sub)})")

    write(df)


if __name__ == "__main__":
    main()
