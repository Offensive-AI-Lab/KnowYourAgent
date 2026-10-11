"""Produce every EDA figure from per_attempt.parquet.

Each function writes both PDF and PNG into Data/EDA/figures/.
Run `uv run python Data/EDA/figures.py` to produce them all.
"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
PQ = HERE / "parquet" / "per_attempt.parquet"
FIG = HERE / "figures"
TAB = HERE / "tables"
FIG.mkdir(parents=True, exist_ok=True)
TAB.mkdir(parents=True, exist_ok=True)

SUITES = ["banking", "slack", "travel", "workspace"]
SUITE_COLORS = {"banking": "#1f77b4", "slack": "#2ca02c", "travel": "#d62728", "workspace": "#9467bd"}
ASSET_ORDER = [
    "no_knowledge",
    "benign_response",
    "user_persona",
    "type_of_agent",
    "model_identity",
    "behavioral_rules",
    "tool_names_and_parameters",
    "defenses",
    "agent_task",
    "injected_tool_output",
    "exception_schema",
    "multi__behavioral_rules__tool_names_and_parameters",
    "multi__filters__guardrails__structural_defenses",
]
ATTACK_ORDER = [
    "ignorprev",
    "topicattack",
    "chatinject",
    "agentvigil",
    "cobra_norecon",
    "cobra_full",
]
DEFENSE_ORDER = ["none", "transformers_pi_detector", "repeat_user_prompt", "spotlighting_with_delimiting"]

plt.rcParams.update({
    "figure.dpi": 130,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "legend.fontsize": 9,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
})


def _save(fig, name: str):
    fig.savefig(FIG / f"{name}.pdf")
    fig.savefig(FIG / f"{name}.png")
    plt.close(fig)
    print(f"  -> {FIG / name}.pdf  +  .png")


def load() -> pd.DataFrame:
    df = pd.read_parquet(PQ)
    df = df.copy()
    # Normalize NA in attempts
    df["attempt_idx"] = df["attempt_idx"].fillna(0).astype(int)
    # Helper bool->float for plotting
    df["security_f"] = df["security"].astype("Float64").astype(float)
    df["utility_f"] = df["utility"].astype("Float64").astype(float)
    return df


# ---------------------------------------------------------------------------
# Figure 3 candidates
# ---------------------------------------------------------------------------

def _bootstrap_mean_ci(values, n=2000, seed=0):
    if len(values) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    boots = rng.choice(values, size=(n, len(values)), replace=True).mean(axis=1)
    return float(np.mean(values)), float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))


def fig3a_recon_lift_scatter(df: pd.DataFrame) -> None:
    """Per-task scatter: x = no_knowledge security, y = best-knowledge security."""
    ak = df[df.framework == "asr_knowledge"].copy()
    # Use no_defense baseline; collapse on (suite, UT, IJ)
    base = (ak[(ak.knowledge_set == "no_knowledge") & (ak.defense == "no_defense")]
            .groupby(["suite", "user_task_id", "injection_task_id"])["security_f"]
            .mean().rename("base").reset_index())
    # Best across all single + multi assets at no_defense
    best = (ak[(ak.defense == "no_defense") & (ak.knowledge_set != "no_knowledge")]
            .groupby(["suite", "user_task_id", "injection_task_id"])["security_f"]
            .max().rename("best").reset_index())
    merged = base.merge(best, on=["suite", "user_task_id", "injection_task_id"])

    fig, ax = plt.subplots(figsize=(7.0, 5.6))
    rng = np.random.default_rng(0)
    for s in SUITES:
        sub = merged[merged.suite == s]
        if sub.empty:
            continue
        jx = sub["base"] + rng.normal(0, 0.025, len(sub))
        jy = sub["best"] + rng.normal(0, 0.025, len(sub))
        ax.scatter(jx, jy, label=f"{s} (n={len(sub)})",
                   color=SUITE_COLORS[s], s=42, alpha=0.65,
                   edgecolor="white", linewidth=0.5)
    ax.plot([-0.05, 1.05], [-0.05, 1.05], "k--", lw=0.8, alpha=0.5)
    ax.set_xlim(-0.08, 1.08); ax.set_ylim(-0.08, 1.08)
    ax.set_xlabel("ASR with no-knowledge attacker")
    ax.set_ylabel("ASR with best single knowledge asset")
    ax.set_title("Reconnaissance lifts hard tasks the most\n(each dot = one (user_task, injection_task) pair, no defense)")
    ax.legend(loc="lower right", frameon=False)
    # Annotate "above-diagonal = recon helps"
    ax.text(0.05, 0.95, "recon helps", transform=ax.transAxes, fontsize=10,
            color="#2ca02c", va="top")
    ax.text(0.55, 0.05, "recon doesn't change much", transform=ax.transAxes,
            fontsize=10, color="#666", ha="left")

    # Inset: bar chart of mean lift by no_knowledge-ASR quartile
    ins = ax.inset_axes([0.55, 0.12, 0.40, 0.30])
    merged["lift"] = merged["best"] - merged["base"]
    # Quartile bins on base
    bins = [-0.01, 0.0001, 0.25, 0.5, 0.75, 1.0001]
    labels = ["0%", "0-25%", "25-50%", "50-75%", "75-100%"]
    merged["q"] = pd.cut(merged["base"], bins=bins, labels=labels, include_lowest=True)
    qstats = merged.groupby("q", observed=False)["lift"].agg(["mean", "count", "sem"]).reset_index()
    qstats = qstats.dropna(subset=["mean"])
    ins.bar(list(range(len(qstats))), qstats["mean"].values, yerr=qstats["sem"].values,
            color="#7f7f7f", capsize=2, tick_label=qstats["q"].astype(str).tolist())
    ymax = float(qstats["mean"].max()) if len(qstats) else 0.5
    ins.set_ylim(0, max(0.5, ymax * 1.2))
    ins.set_ylabel("avg recon lift", fontsize=8)
    ins.set_xlabel("no-knowledge ASR quartile", fontsize=8)
    ins.tick_params(labelsize=7)
    ins.set_title("recon lift vs task difficulty", fontsize=8)
    _save(fig, "fig3a_recon_lift_scatter")

    # Also dump table
    merged.to_csv(TAB / "fig3a_recon_lift_per_task.csv", index=False)
    qstats.to_csv(TAB / "fig3a_recon_lift_quartiles.csv", index=False)


def fig3b_asset_hierarchy_roi(df: pd.DataFrame) -> None:
    """Asset Δ hierarchy bars + greedy ROI curve."""
    ak = df[df.framework == "asr_knowledge"].copy()
    # Cell ASR per (suite, asset, defense)
    cells = (ak.groupby(["suite", "knowledge_set", "defense"])["security_f"]
             .mean().reset_index().rename(columns={"security_f": "asr"}))
    base = cells[cells.knowledge_set == "no_knowledge"].rename(columns={"asr": "base"})[
        ["suite", "defense", "base"]]
    cells = cells.merge(base, on=["suite", "defense"], how="left")
    cells["delta"] = cells["asr"] - cells["base"]
    cells = cells[cells.knowledge_set != "no_knowledge"].copy()

    # Order assets by mean Δ across suites (no_defense)
    order = (cells[cells.defense == "no_defense"]
             .groupby("knowledge_set")["delta"].mean()
             .sort_values(ascending=True).index.tolist())

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.0), gridspec_kw={"width_ratios": [1.0, 0.85]})

    # Panel A: horizontal bars, faceted hue=defense, color by suite
    pa = axes[0]
    pivot = cells.pivot_table(index="knowledge_set", columns=["defense", "suite"], values="delta")
    pivot = pivot.reindex(order)
    bw = 0.16
    yticks = np.arange(len(order))
    defenses_present = [d for d in ["no_defense", "repeat_user_prompt"] if d in cells.defense.unique()]
    for i, defn in enumerate(defenses_present):
        for j, s in enumerate(SUITES):
            col = (defn, s)
            if col not in pivot.columns:
                continue
            vals = pivot[col].values
            offset = (i * len(SUITES) + j - (len(defenses_present) * len(SUITES) - 1) / 2) * bw
            edge = "k" if defn == "repeat_user_prompt" else None
            hatch = "//" if defn == "repeat_user_prompt" else None
            pa.barh(yticks + offset, vals, height=bw,
                    color=SUITE_COLORS.get(s, "#888"),
                    edgecolor=edge, linewidth=0.4, hatch=hatch,
                    label=f"{s} | {defn}" if j == 0 or defn == defenses_present[0] else None)
    pa.set_yticks(yticks)
    pa.set_yticklabels([k.replace("_", " ") for k in order])
    pa.axvline(0, color="k", lw=0.6)
    pa.set_xlabel("ASR Δ vs no-knowledge baseline")
    pa.set_title("(a) Knowledge-asset hierarchy")
    # legend: suite colors + defense hatch
    suite_handles = [plt.Rectangle((0, 0), 1, 1, color=SUITE_COLORS[s]) for s in SUITES]
    def_handles = [plt.Rectangle((0, 0), 1, 1, color="#bbb"),
                   plt.Rectangle((0, 0), 1, 1, color="#bbb", hatch="//", edgecolor="k")]
    pa.legend(suite_handles + def_handles,
              SUITES + ["no defense", "repeat user prompt"],
              loc="lower right", frameon=False, fontsize=8)

    # Panel B: greedy cumulative ROI curve per (suite, defense)
    pb = axes[1]
    for defn in defenses_present:
        for s in SUITES:
            sub = cells[(cells.defense == defn) & (cells.suite == s)].copy()
            if sub.empty:
                continue
            # Greedy: sort by delta desc
            sub = sub.sort_values("delta", ascending=False).reset_index(drop=True)
            xs = np.arange(0, len(sub) + 1)
            base_val = base[(base.suite == s) & (base.defense == defn)]["base"].mean()
            cum = [base_val]
            running_unattacked = 1 - base_val
            for d in sub["delta"]:
                d_clipped = max(0.0, d)
                # Lower-bound under "asset successes are independent": multiply unattacked
                running_unattacked *= (1 - d_clipped / max(running_unattacked, 1e-6))
                running_unattacked = max(min(running_unattacked, 1.0), 0.0)
                cum.append(1 - running_unattacked)
            line_style = "-" if defn == "no_defense" else "--"
            pb.plot(xs, cum, marker="o", color=SUITE_COLORS[s], linestyle=line_style,
                    alpha=0.85, lw=1.2, ms=4,
                    label=f"{s} | {defn}" if defn == "no_defense" else None)
    pb.set_xlabel("# of knowledge assets added (greedy)")
    pb.set_ylabel("Projected ASR (independence lower bound)")
    pb.set_title("(b) Greedy recon ROI")
    pb.set_ylim(0, 1.0)
    pb.legend(loc="lower right", frameon=False)
    pb.grid(True, alpha=0.25)
    plt.tight_layout()
    _save(fig, "fig3b_asset_hierarchy_roi")

    cells.to_csv(TAB / "fig3b_asset_delta.csv", index=False)


def fig3c_asset_defense_matrix(df: pd.DataFrame) -> None:
    """Heatmap: rows = assets, cols = (suite, defense). Cell = ASR."""
    ak = df[df.framework == "asr_knowledge"].copy()
    cells = (ak.groupby(["suite", "knowledge_set", "defense"])["security_f"]
             .mean().reset_index().rename(columns={"security_f": "asr"}))
    counts = (ak.groupby(["suite", "knowledge_set", "defense"])["security"]
              .count().reset_index().rename(columns={"security": "n"}))
    cells = cells.merge(counts, on=["suite", "knowledge_set", "defense"])
    cells["col"] = cells["suite"] + " / " + cells["defense"].str.replace("_", " ")
    pivot = cells.pivot(index="knowledge_set", columns="col", values="asr")
    n_pivot = cells.pivot(index="knowledge_set", columns="col", values="n").fillna(0).astype(int)
    # Order rows
    present = [a for a in ASSET_ORDER if a in pivot.index]
    pivot = pivot.reindex(present)
    n_pivot = n_pivot.reindex(present)
    # Order cols
    desired_cols = []
    for s in SUITES:
        for d in ["no defense", "repeat user prompt"]:
            c = f"{s} / {d}"
            if c in pivot.columns:
                desired_cols.append(c)
    pivot = pivot[desired_cols]
    n_pivot = n_pivot[desired_cols]
    fig, ax = plt.subplots(figsize=(11, 6.5))
    annot = pivot.map(lambda v: "—" if pd.isna(v) else f"{v:.2f}")
    sns.heatmap(pivot, annot=annot.values, fmt="", cmap="Reds", vmin=0, vmax=0.8,
                cbar_kws={"label": "ASR"}, linewidths=0.4, linecolor="white", ax=ax)
    # bold cells where ASR(repeat) > ASR(no_defense) — counterintuitive
    for i, asset in enumerate(present):
        for s_idx, s in enumerate(SUITES):
            cdef = f"{s} / no defense"
            crep = f"{s} / repeat user prompt"
            if cdef in pivot.columns and crep in pivot.columns:
                a = pivot.at[asset, cdef]
                b = pivot.at[asset, crep]
                if pd.notna(a) and pd.notna(b) and b > a + 0.01:
                    j = pivot.columns.get_loc(crep)
                    ax.add_patch(Rectangle((j, i), 1, 1, fill=False, edgecolor="#1a9850", lw=2.4))
    ax.set_ylabel("Knowledge asset")
    ax.set_xlabel("(suite / defense)")
    ax.set_title("Asset × Defense ASR — green box: asset gains ASR under defense (counterintuitive)")
    plt.setp(ax.get_xticklabels(), rotation=35, ha="right")
    plt.tight_layout()
    _save(fig, "fig3c_asset_defense_matrix")
    pivot.to_csv(TAB / "fig3c_asset_defense_matrix.csv")
    n_pivot.to_csv(TAB / "fig3c_asset_defense_matrix_n.csv")


def fig3d_super_additivity(df: pd.DataFrame) -> None:
    """Banking only: compare observed multi-asset ASR vs independence-predicted."""
    ak = df[(df.framework == "asr_knowledge") & (df.suite == "banking")].copy()
    cells = (ak.groupby(["knowledge_set", "defense"])["security_f"]
             .mean().reset_index().rename(columns={"security_f": "asr"}))
    base = cells[cells.knowledge_set == "no_knowledge"].set_index("defense")["asr"]
    multi_keys = [k for k in cells["knowledge_set"].unique() if k.startswith("multi__")]
    if not multi_keys:
        return
    fig, axes = plt.subplots(1, len(multi_keys), figsize=(6.2 * len(multi_keys), 4.6),
                             squeeze=False)
    summary_rows = []
    for ax_i, mkey in enumerate(multi_keys):
        ax = axes[0, ax_i]
        components = mkey.replace("multi__", "").split("__")
        for d_i, defn in enumerate(["no_defense", "repeat_user_prompt"]):
            sub = cells[cells.defense == defn]
            if mkey not in sub["knowledge_set"].values:
                continue
            obs = sub[sub.knowledge_set == mkey]["asr"].iloc[0]
            base_v = base.get(defn, 0.0)
            # Predicted under independence:
            #   P_success = 1 - prod(1 - delta_i) where delta_i = ASR(asset_i) - ASR(no_knowledge)
            unattacked = 1.0 - base_v
            covered = unattacked
            for comp in components:
                if comp not in sub["knowledge_set"].values:
                    continue
                comp_asr = sub[sub.knowledge_set == comp]["asr"].iloc[0]
                lift = max(0.0, comp_asr - base_v)
                # Probability of failure given lift on top of baseline:
                covered *= (1 - lift / max(unattacked, 1e-6))
            pred = 1 - covered
            xpos = d_i
            ax.bar(xpos - 0.18, pred, width=0.34, color="#aaa", label="predicted (independence)" if d_i == 0 else None)
            ax.bar(xpos + 0.18, obs, width=0.34, color="#d62728", label="observed" if d_i == 0 else None)
            ax.text(xpos - 0.18, pred + 0.01, f"{pred:.2f}", ha="center", fontsize=8)
            ax.text(xpos + 0.18, obs + 0.01, f"{obs:.2f}", ha="center", fontsize=8)
            ax.text(xpos, max(obs, pred) + 0.06,
                    f"synergy:\n{(obs - pred):+0.2f}",
                    ha="center", fontsize=9,
                    color="#1a9850" if obs > pred else "#c92020", fontweight="bold")
            summary_rows.append({
                "combo": mkey, "defense": defn,
                "predicted": pred, "observed": obs, "synergy": obs - pred,
            })
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["no defense", "repeat user prompt"])
        ax.set_ylim(0, 1.0)
        ax.set_ylabel("ASR")
        ax.set_title(f"banking — combo: {', '.join(components)}", fontsize=10)
        ax.legend(loc="upper left", frameon=False, fontsize=8)
    fig.suptitle("Super-additivity test: multi-asset recon vs independence prediction (banking)", y=1.02)
    plt.tight_layout()
    _save(fig, "fig3d_super_additivity")
    pd.DataFrame(summary_rows).to_csv(TAB / "fig3d_super_additivity.csv", index=False)


# ---------------------------------------------------------------------------
# Auxiliary figures
# ---------------------------------------------------------------------------

def _attack_family(row) -> str:
    """Roll up framework + cobra_variant into a paper-shape attack name."""
    fw = row.framework
    if isinstance(fw, str) and fw.startswith("cobra"):
        v = row.cobra_variant
        if isinstance(v, str) and ("NoRecon" in v or "NoTactics" in v):
            return "cobra_ablate"
        return "cobra_full"
    return fw if isinstance(fw, str) else "unknown"


def aux1_cross_baseline_landscape(df: pd.DataFrame) -> None:
    """Grouped bar chart: ASR per (framework, suite), no-defense, gpt-4.1."""
    sub = df[(df.defense == "none") & ((df.model == "gpt-4.1") | df.model.isna())].copy()
    # Use only Cobra V3 FullAgent for "cobra_full"; ignore older versions for the headline plot.
    sub = sub[~((sub.framework.str.startswith("cobra")) & (~sub.framework.isin(["cobra_v3", "cobra_v4"])))]
    sub["attack"] = sub.apply(_attack_family, axis=1)
    valid = sub[sub.security.notna()]
    g = valid.groupby(["attack", "suite"])["security_f"].agg(["mean", "count"]).reset_index()
    g = g[g["count"] >= 10]  # drop tiny cells

    attacks = [a for a in ATTACK_ORDER if a in g["attack"].unique()] + \
              [a for a in g["attack"].unique() if a not in ATTACK_ORDER]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    bw = 0.18
    x = np.arange(len(attacks))
    for i, s in enumerate(SUITES):
        vals = [g[(g.attack == a) & (g.suite == s)]["mean"].mean() if not g[(g.attack == a) & (g.suite == s)].empty else np.nan
                for a in attacks]
        ax.bar(x + (i - 1.5) * bw, vals, bw, label=s, color=SUITE_COLORS[s])
    ax.set_xticks(x)
    ax.set_xticklabels(attacks, rotation=15)
    ax.set_ylabel("ASR (no defense, gpt-4.1)")
    ax.set_title("Cross-baseline ASR landscape — paper Table II visualizer")
    ax.legend(frameon=False, ncols=4)
    ax.set_ylim(0, 1.0)
    ax.grid(True, axis="y", alpha=0.25)
    # n annotations
    for i, a in enumerate(attacks):
        for j, s in enumerate(SUITES):
            n_match = g[(g.attack == a) & (g.suite == s)]["count"]
            if not n_match.empty:
                n = int(n_match.values[0])
                v = g[(g.attack == a) & (g.suite == s)]["mean"].iloc[0]
                ax.text(i + (j - 1.5) * bw, v + 0.015, f"n={n}", ha="center", fontsize=7, color="#444")
    plt.tight_layout()
    _save(fig, "aux1_cross_baseline_landscape")
    g.to_csv(TAB / "aux1_cross_baseline_landscape.csv", index=False)


def aux2_defense_bypass_heatmap(df: pd.DataFrame) -> None:
    """4 panels (one per suite), rows=attack, cols=defense, cell=ASR."""
    sub = df.copy()
    sub["attack"] = sub.apply(_attack_family, axis=1)
    valid = sub[sub.security.notna()]
    fig, axes = plt.subplots(1, 4, figsize=(16, 4.5), sharey=True)
    attacks = [a for a in ATTACK_ORDER if a in valid["attack"].unique()] + \
              [a for a in valid["attack"].unique() if a not in ATTACK_ORDER and a != "asr_knowledge"]
    if "asr_knowledge" in valid["attack"].unique():
        attacks.append("asr_knowledge")
    for i, s in enumerate(SUITES):
        ax = axes[i]
        ssub = valid[valid.suite == s]
        pivot = ssub.groupby(["attack", "defense"])["security_f"].mean().unstack("defense")
        # Order columns
        cols = [d for d in DEFENSE_ORDER if d in pivot.columns] + \
               [d for d in pivot.columns if d not in DEFENSE_ORDER]
        rows = [a for a in attacks if a in pivot.index]
        pivot = pivot.reindex(index=rows, columns=cols)
        annot = pivot.map(lambda v: "—" if pd.isna(v) else f"{v:.2f}")
        sns.heatmap(pivot, annot=annot.values, fmt="", cmap="OrRd", vmin=0, vmax=1.0,
                    cbar=(i == 3), cbar_kws={"label": "ASR"} if i == 3 else None,
                    linewidths=0.3, linecolor="white", ax=ax)
        ax.set_title(s)
        ax.set_xlabel("defense")
        ax.set_ylabel("attack" if i == 0 else "")
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    fig.suptitle("Defense bypass heatmap — Table III visualizer (cell = ASR)", y=1.02)
    plt.tight_layout()
    _save(fig, "aux2_defense_bypass_heatmap")


def aux3_convergence_curves(df: pd.DataFrame) -> None:
    """Cumulative ASR vs attack-attempt index for multi-attempt frameworks."""
    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    # Cobra: attempts logged inside each .ans
    cobra = df[df.framework.isin(["cobra_v3"])].copy()
    # Per case = unique (raw_path), success_at_attempt = first attempt where security=True
    def first_success(g):
        s = g[g.security == True]
        if s.empty:
            return None
        return s["attempt_idx"].min()
    cob_cases = cobra.groupby("raw_path").apply(first_success).reset_index(name="success_at")
    n_total_cobra = len(cob_cases)
    max_attempt = int(max(1, cobra["attempt_idx"].max() or 1))
    xs = np.arange(1, max_attempt + 1)
    cum = [(cob_cases["success_at"].dropna() <= a).sum() / max(n_total_cobra, 1) for a in xs]
    ax.plot(xs, cum, marker="o", color="#d62728", label=f"cobra_v3 (n={n_total_cobra})", lw=2)

    # Agentvigil: iteration index
    av = df[df.framework == "agentvigil"].copy()
    if not av.empty and av["attempt_idx"].notna().any():
        av["case_key"] = av["suite"].astype(str) + "/" + av["user_task_id"].astype(str) + "/" + av["injection_task_id"].astype(str)
        av_cases = av.groupby("case_key").apply(lambda g: g[g.security == True]["attempt_idx"].min() if (g.security == True).any() else None).reset_index(name="success_at")
        n_av = len(av_cases)
        max_iter = int(max(1, av["attempt_idx"].max() or 1))
        xs2 = np.arange(0, max_iter + 1)
        cum2 = [(av_cases["success_at"].dropna() <= a).sum() / max(n_av, 1) for a in xs2]
        ax.plot(xs2, cum2, marker="s", color="#1f77b4", label=f"agentvigil (n={n_av})", lw=2)

    # ASR-Knowledge full Cobra-like: average over (knowledge sets) as "best so far"
    # Each cell ~ one attempt; cumulative across asset count is in fig3b. We omit here.

    # Static baselines: chatinject / ignorprev have one attempt only -> horizontal line.
    for fw, color in [("chatinject", "#7f7f7f"), ("ignorprev", "#bbbb22"), ("topicattack", "#888")]:
        sub = df[(df.framework == fw) & (df.defense == "none")]
        if sub.empty or sub["security"].isna().all():
            continue
        v = sub["security_f"].mean()
        ax.axhline(v, color=color, ls=":", lw=1.4, alpha=0.85,
                   label=f"{fw} (static, ASR={v:.2f})")
    ax.set_xlabel("attack attempts")
    ax.set_ylabel("cumulative ASR (case-level)")
    ax.set_title("Convergence: how many attempts does each baseline need?")
    ax.set_ylim(0, 1.0)
    ax.legend(frameon=False, loc="lower right")
    ax.grid(True, alpha=0.25)
    plt.tight_layout()
    _save(fig, "aux3_convergence_curves")


def aux4_payload_morphology(df: pd.DataFrame) -> None:
    """Distribution shifts of payload features across frameworks and Cobra versions."""
    import string
    p = df.copy()
    p = p[p["payload"].notna() & (p["payload_len"] > 0)]
    # Map framework groups
    def fw_label(row):
        if row.framework.startswith("cobra"):
            return f"cobra v{row.framework[-1]}"
        return row.framework
    p["fw"] = p.apply(fw_label, axis=1)

    def all_caps_ratio(s: str) -> float:
        letters = [c for c in s if c.isalpha()]
        if not letters:
            return 0
        return sum(1 for c in letters if c.isupper()) / len(letters)

    def has_token(s: str, pat) -> bool:
        return bool(pat.search(s))

    SYSTEM_PAT = re.compile(r"system|admin|override|urgent|important", re.IGNORECASE)
    XML_PAT = re.compile(r"<(system|user|assistant|admin)>", re.IGNORECASE)
    ENC_PAT = re.compile(r"\b(uno|dous|trois|quattro|cinq|sixus|sept|huit|neuf|zeru)\b", re.IGNORECASE)

    p["len"] = p["payload"].str.len()
    p["caps_ratio"] = p["payload"].apply(all_caps_ratio)
    p["has_system_word"] = p["payload"].apply(lambda s: has_token(s, SYSTEM_PAT))
    p["has_xml_tag"] = p["payload"].apply(lambda s: has_token(s, XML_PAT))
    p["has_enc"] = p["payload"].apply(lambda s: has_token(s, ENC_PAT))

    # Pick families in narrative order
    order = ["ignorprev", "topicattack", "agentvigil", "chatinject", "cobra v1", "cobra v2", "cobra v3", "cobra v4"]
    families = [f for f in order if f in p["fw"].unique()]

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    # Panel A: payload length boxplot
    ax = axes[0, 0]
    data = [p[p.fw == f]["len"].clip(upper=12000) for f in families]
    bp = ax.boxplot(data, tick_labels=families, vert=True, showfliers=False, patch_artist=True)
    for box, fam in zip(bp["boxes"], families):
        box.set_facecolor("#cccccc" if "cobra" not in fam else "#fbb4ae")
    ax.set_ylabel("payload chars (clip @ 12k)")
    ax.set_title("(a) payload length")
    plt.setp(ax.get_xticklabels(), rotation=20)

    # Panel B: caps ratio
    ax = axes[0, 1]
    data = [p[p.fw == f]["caps_ratio"] for f in families]
    bp = ax.boxplot(data, tick_labels=families, showfliers=False, patch_artist=True)
    for box, fam in zip(bp["boxes"], families):
        box.set_facecolor("#cccccc" if "cobra" not in fam else "#fbb4ae")
    ax.set_ylabel("ALL-CAPS letter share")
    ax.set_title("(b) caps ratio")
    plt.setp(ax.get_xticklabels(), rotation=20)

    # Panel C/D: token presence by family
    ax = axes[1, 0]
    feat_rates = p.groupby("fw")[["has_system_word", "has_xml_tag", "has_enc"]].mean()
    feat_rates = feat_rates.reindex(families)
    feat_rates.plot(kind="bar", ax=ax, width=0.78, color=["#1f77b4", "#2ca02c", "#d62728"])
    ax.set_ylabel("share of payloads")
    ax.set_title("(c) presence of theatrical tokens")
    ax.legend(["urgency/system words", "xml/role tags", "digit encoding"], frameon=False, fontsize=8)
    plt.setp(ax.get_xticklabels(), rotation=20)

    # Panel D: how length predicts ASR within Cobra/asr_knowledge
    ax = axes[1, 1]
    target = p[(p.framework.isin(["asr_knowledge"]) | p.framework.str.startswith("cobra"))
               & (p.security.notna())].copy()
    target = target[target["len"] <= 12000]
    if not target.empty:
        bins = np.linspace(0, 12000, 13)
        target["bin"] = pd.cut(target["len"], bins=bins, include_lowest=True)
        gg = target.groupby("bin", observed=False)["security_f"].agg(["mean", "count"]).reset_index()
        gg = gg[gg["count"] >= 30]
        ax.errorbar(gg["bin"].apply(lambda b: b.mid).astype(float), gg["mean"],
                    yerr=np.sqrt(gg["mean"] * (1 - gg["mean"]) / gg["count"]),
                    marker="o", color="#666")
    ax.set_xlabel("payload length (chars)")
    ax.set_ylabel("ASR (binned)")
    ax.set_title("(d) length vs ASR (cobra + asr_knowledge)")
    plt.tight_layout()
    _save(fig, "aux4_payload_morphology")

    p[["framework", "fw", "suite", "len", "caps_ratio", "has_system_word", "has_xml_tag", "has_enc", "security_f"]].to_parquet(
        HERE / "parquet" / "payload_features.parquet", index=False)


def aux5_ut_ij_heatmap(df: pd.DataFrame) -> None:
    """Per-suite clustermaps showing which UTs / IJs are universally vulnerable."""
    # Use Cobra-V3 FullAgent + ASR-Knowledge full assets pooled as the "anyone tries best" view.
    sub = df[(df.framework.isin(["cobra_v3", "asr_knowledge"]))
             & (df.security.notna())].copy()
    sub = sub[(sub.cobra_variant.isna()) | (~sub.cobra_variant.isin(["NoRecon", "NoTactics"]))]
    for suite in SUITES:
        ssub = sub[sub.suite == suite]
        if ssub.empty:
            continue
        agg = (ssub.groupby(["user_task_id", "injection_task_id"])["security_f"]
               .mean().reset_index())
        pivot = agg.pivot(index="user_task_id", columns="injection_task_id", values="security_f")
        if pivot.shape[0] < 2 or pivot.shape[1] < 2:
            continue
        try:
            cg = sns.clustermap(pivot.fillna(0), cmap="rocket_r", vmin=0, vmax=1,
                                figsize=(7.5, 8.5),
                                cbar_kws={"label": "ASR"},
                                metric="euclidean", method="average",
                                linewidths=0.2)
        except Exception:
            cg = sns.clustermap(pivot.fillna(0), cmap="rocket_r", vmin=0, vmax=1,
                                figsize=(7.5, 8.5), row_cluster=False, col_cluster=False)
        cg.fig.suptitle(f"UT × IJ vulnerability — {suite}", y=1.02)
        cg.ax_heatmap.set_xlabel("injection_task_id")
        cg.ax_heatmap.set_ylabel("user_task_id")
        cg.savefig(FIG / f"aux5_ut_ij_clustermap_{suite}.pdf")
        cg.savefig(FIG / f"aux5_ut_ij_clustermap_{suite}.png")
        plt.close(cg.fig)
        print(f"  -> aux5_ut_ij_clustermap_{suite}.pdf")


def aux6_failure_taxonomy(df: pd.DataFrame, do_llm: bool = False) -> None:
    """Without LLM: use evaluator_label from Cobra .ans logs.
    With LLM: classify ASR-Knowledge transcripts. (do_llm=False default)."""
    sub = df[df.framework.str.startswith("cobra")].copy()
    # Restrict to the 4 AgentDojo suites (drop InjecAgent dh/ds confound).
    sub = sub[sub.suite.isin(SUITES)]
    sub = sub[sub.evaluator_label.notna()]
    if sub.empty:
        # No evaluator labels — write a stub
        with open(TAB / "aux6_failure_taxonomy_README.md", "w") as f:
            f.write("No Cobra evaluator labels parsed; LLM-classified taxonomy not run.\n")
        return
    # Roll up rare labels
    label_map = {
        "SUCCESS": "success",
        "STRATEGY_SELECTION_FAILURE": "strategy_selection_failure",
        "STRATEGY_EXECUTION_FAILURE": "strategy_execution_failure",
        "GUARDRAILS_FAILURE": "guardrails_failure",
    }
    sub["label"] = sub["evaluator_label"].map(label_map).fillna("other")
    # Per (defense, suite) stacked bar
    sub = sub[sub.defense.isin(["none", "repeat_user_prompt", "spotlighting_with_delimiting"])]
    sub["facet"] = sub["defense"] + " | " + sub["suite"].fillna("?")
    counts = sub.groupby(["facet", "label"]).size().unstack("label").fillna(0)
    # Order labels
    label_order = ["success", "strategy_selection_failure", "strategy_execution_failure",
                   "guardrails_failure", "other"]
    label_order = [l for l in label_order if l in counts.columns]
    counts = counts[label_order]
    pct = counts.div(counts.sum(axis=1), axis=0)
    fig, ax = plt.subplots(figsize=(11, 6))
    colors = {"success": "#2ca02c", "strategy_selection_failure": "#aaaaaa",
              "strategy_execution_failure": "#888888", "guardrails_failure": "#d62728",
              "other": "#dddddd"}
    pct.plot(kind="bar", stacked=True, ax=ax,
             color=[colors.get(l, "#999") for l in label_order])
    ax.set_ylabel("share of attempts")
    ax.set_xlabel("defense | suite")
    ax.set_title("Failure-mode taxonomy across Cobra evaluator labels")
    ax.legend(frameon=False, loc="upper right", fontsize=8)
    plt.setp(ax.get_xticklabels(), rotation=35, ha="right")
    plt.tight_layout()
    _save(fig, "aux6_failure_taxonomy")
    counts.to_csv(TAB / "aux6_failure_taxonomy_counts.csv")


def aux7_cost_pareto(df: pd.DataFrame) -> None:
    """ASR vs avg payload length per (framework, defense). Highlight Pareto front."""
    sub = df.copy()
    sub["attack"] = sub.apply(_attack_family, axis=1)
    sub = sub[sub.security.notna()]
    g = sub.groupby(["attack", "defense"]).agg(asr=("security_f", "mean"),
                                                avg_len=("payload_len", "mean"),
                                                n=("security_f", "size")).reset_index()
    g = g[(g["n"] >= 10) & (g["avg_len"] > 50)]  # drop cells with no payload-length data
    fig, ax = plt.subplots(figsize=(9, 5.5))
    markers = {"none": "o", "repeat_user_prompt": "s",
               "transformers_pi_detector": "^", "spotlighting_with_delimiting": "D"}
    attacks_seen = sorted(g["attack"].unique())
    palette = sns.color_palette("tab10", n_colors=max(len(attacks_seen), 3))
    color_for = {a: palette[i % len(palette)] for i, a in enumerate(attacks_seen)}
    for _, row in g.iterrows():
        ax.scatter(row["avg_len"], row["asr"],
                   s=80 + np.clip(row["n"], 0, 1500) / 12,
                   marker=markers.get(row["defense"], "x"),
                   color=color_for[row["attack"]],
                   edgecolor="black", linewidth=0.5, alpha=0.85)
        ax.text(row["avg_len"] * 1.04, row["asr"] + 0.013,
                f"{row['attack']}\n{row['defense'][:11]}",
                fontsize=7, color=color_for[row["attack"]])
    ax.set_xscale("log")
    ax.set_xlabel("avg payload length (chars, log scale)")
    ax.set_ylabel("ASR")
    ax.set_title("Cost–effectiveness: ASR vs payload size (point size ∝ n)")
    ax.set_ylim(0, 1.0)
    ax.grid(True, which="both", alpha=0.25)
    # Pareto frontier (lower-cost OR higher-ASR is better — find non-dominated)
    points = g[["avg_len", "asr"]].values
    front = []
    for i, (x, y) in enumerate(points):
        dominated = False
        for j, (x2, y2) in enumerate(points):
            if i == j:
                continue
            if x2 <= x and y2 >= y and (x2 < x or y2 > y):
                dominated = True
                break
        if not dominated:
            front.append((x, y))
    front.sort()
    if front:
        xs, ys = zip(*front)
        ax.plot(xs, ys, "k--", lw=1, alpha=0.6, label="Pareto front")
    # Build legend manually: one entry per (attack color), one per (defense marker)
    attack_handles = [plt.Line2D([0], [0], marker="o", linestyle="",
                                  markerfacecolor=color_for[a], markeredgecolor="black",
                                  markersize=8, label=a) for a in attacks_seen]
    defense_handles = [plt.Line2D([0], [0], marker=markers[d], linestyle="",
                                    markerfacecolor="#aaa", markeredgecolor="black",
                                    markersize=8, label=d.replace("_", " "))
                       for d in markers if d in g["defense"].unique()]
    leg1 = ax.legend(handles=attack_handles, title="attack", loc="upper left",
                     fontsize=8, frameon=False)
    ax.add_artist(leg1)
    ax.legend(handles=defense_handles, title="defense", loc="upper right",
              fontsize=8, frameon=False)
    ax.set_xlim(70, 12000)  # avoid stray text artists expanding the canvas
    plt.tight_layout()
    fig.savefig(FIG / "aux7_cost_pareto.pdf", bbox_inches=None)
    fig.savefig(FIG / "aux7_cost_pareto.png", dpi=130, bbox_inches=None)
    plt.close(fig)
    print(f"  -> {FIG / 'aux7_cost_pareto.pdf'}  +  .png")
    g.to_csv(TAB / "aux7_cost_pareto.csv", index=False)


def fig3a_v2_difficulty_bars(df: pd.DataFrame) -> None:
    """Refined Fig 3a: difficulty-binned recon lift bars + slope distribution.

    Replaces the bimodal scatter with a clearer 2-panel design:
      (a) per-suite bars of mean recon lift, split by no-knowledge difficulty bucket
      (b) violin/strip showing the actual per-pair lift distribution per bucket
    """
    ak = df[df.framework == "asr_knowledge"].copy()
    # Use no_defense for the base. Use best single asset (no multi) for the recon target.
    no_def = ak[ak.defense == "no_defense"]
    base = (no_def[no_def.knowledge_set == "no_knowledge"]
            .groupby(["suite", "user_task_id", "injection_task_id"])["security_f"]
            .mean().rename("base").reset_index())
    best = (no_def[(no_def.knowledge_set != "no_knowledge")
                   & (~no_def.knowledge_set.str.startswith("multi__"))]
            .groupby(["suite", "user_task_id", "injection_task_id"])["security_f"]
            .max().rename("best").reset_index())
    merged = base.merge(best, on=["suite", "user_task_id", "injection_task_id"])
    merged["lift"] = merged["best"] - merged["base"]
    # Difficulty buckets on base ASR (since data is mostly bimodal, use 3 buckets)
    def bucket(v):
        if v <= 0.05:
            return "Robust\n(base ≤ 5%)"
        elif v >= 0.95:
            return "Already broken\n(base ≥ 95%)"
        else:
            return "Mixed\n(5–95%)"
    merged["bucket"] = merged["base"].apply(bucket)
    order_buckets = ["Robust\n(base ≤ 5%)", "Mixed\n(5–95%)", "Already broken\n(base ≥ 95%)"]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4), gridspec_kw={"width_ratios": [1.0, 1.05]})

    # Panel A: bars of mean lift by (suite × bucket) with bootstrap 95% CIs
    ax = axes[0]
    bw = 0.20
    bucket_x = np.arange(len(order_buckets))
    summary_rows = []
    for i, s in enumerate(SUITES):
        means, los, his = [], [], []
        for b in order_buckets:
            sub = merged[(merged.suite == s) & (merged.bucket == b)]
            m, lo, hi = _bootstrap_mean_ci(sub["lift"].values)
            means.append(m if not np.isnan(m) else 0.0)
            los.append(0 if np.isnan(m) else m - lo)
            his.append(0 if np.isnan(m) else hi - m)
            summary_rows.append({"suite": s, "bucket": b, "n": len(sub),
                                 "mean_lift": m, "lo": lo, "hi": hi})
        ax.bar(bucket_x + (i - 1.5) * bw, means, bw, yerr=[los, his],
               color=SUITE_COLORS[s], capsize=2, label=s)
    ax.axhline(0, color="k", lw=0.6)
    ax.set_xticks(bucket_x)
    ax.set_xticklabels(order_buckets)
    ax.set_ylabel("Mean recon lift  (best-single-asset ASR − no-knowledge ASR)")
    ax.set_title("(a) Recon helps the robust tasks, hurts the already-broken ones")
    ax.legend(frameon=False, ncols=4, fontsize=8)
    ax.grid(True, axis="y", alpha=0.25)

    # Panel B: per-bucket distribution as strip + boxplot
    ax = axes[1]
    box_data = [merged[merged.bucket == b]["lift"].values for b in order_buckets]
    bp = ax.boxplot(box_data, tick_labels=order_buckets, showfliers=False,
                    patch_artist=True, widths=0.5,
                    medianprops=dict(color="k"))
    for box, b in zip(bp["boxes"], order_buckets):
        c = "#fbb4ae" if "Already" in b else ("#b3cde3" if "Robust" in b else "#ccebc5")
        box.set_facecolor(c)
    # Strip overlay
    rng = np.random.default_rng(0)
    for i, b in enumerate(order_buckets):
        vals = merged[merged.bucket == b]["lift"].values
        if len(vals) == 0:
            continue
        x = np.full(len(vals), i + 1) + rng.normal(0, 0.06, len(vals))
        ax.scatter(x, vals, s=8, alpha=0.30, color="k", linewidths=0)
    ax.axhline(0, color="k", lw=0.6)
    ax.set_ylabel("recon lift per pair")
    ax.set_title("(b) Per-pair lift distribution")
    ax.grid(True, axis="y", alpha=0.25)

    # Headline annotation: cite Spearman + bottom/top means
    from scipy.stats import spearmanr
    rho, p = spearmanr(merged["base"], merged["lift"])
    bottom_mean = merged[merged.bucket == "Robust\n(base ≤ 5%)"]["lift"].mean()
    top_mean = merged[merged.bucket == "Already broken\n(base ≥ 95%)"]["lift"].mean()
    fig.suptitle(
        f"Reconnaissance value flips sign with task difficulty: "
        f"+{bottom_mean*100:.1f}pp on robust tasks vs {top_mean*100:+.1f}pp on already-broken ones "
        f"(ρ = {rho:.3f}, p = {p:.0e}, n = {len(merged)})",
        y=1.02, fontsize=11,
    )
    plt.tight_layout()
    _save(fig, "fig3a_recon_lift_by_difficulty")
    pd.DataFrame(summary_rows).to_csv(TAB / "fig3a_recon_lift_by_difficulty.csv", index=False)


def aux9_spotlighting_backfire(df: pd.DataFrame) -> None:
    """Defense backfire: spotlighting_with_delimiting raises Cobra Full ASR in 4/4 suites."""
    sub = df.copy()
    sub["attack"] = sub.apply(_attack_family, axis=1)
    sub = sub[sub.security.notna() & (sub.attack.isin(["cobra_full", "cobra_ablate", "chatinject", "ignorprev", "topicattack"]))]
    # We use the 4 AgentDojo suites only
    sub = sub[sub.suite.isin(SUITES)]
    g = (sub.groupby(["attack", "defense", "suite"])
         .agg(asr=("security_f", "mean"), n=("security_f", "size")).reset_index())

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.0), gridspec_kw={"width_ratios": [1.2, 1.0]})
    # Panel A: side-by-side bars of Cobra Full ASR per (suite, defense)
    ax = axes[0]
    defenses_to_show = ["none", "repeat_user_prompt", "spotlighting_with_delimiting"]
    bw = 0.27
    x = np.arange(len(SUITES))
    palette = {"none": "#888", "repeat_user_prompt": "#2ca02c", "spotlighting_with_delimiting": "#d62728"}
    for i, d in enumerate(defenses_to_show):
        vals = [(g[(g.attack == "cobra_full") & (g.defense == d) & (g.suite == s)]["asr"].mean()
                 if not g[(g.attack == "cobra_full") & (g.defense == d) & (g.suite == s)].empty
                 else np.nan) for s in SUITES]
        ax.bar(x + (i - 1) * bw, vals, bw, color=palette[d],
               label=d.replace("_", " "),
               edgecolor="k", linewidth=0.3)
        for xi, v in zip(x + (i - 1) * bw, vals):
            if not np.isnan(v):
                ax.text(xi, v + 0.015, f"{v*100:.0f}%", ha="center", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(SUITES)
    ax.set_ylabel("Cobra-Full ASR")
    ax.set_ylim(0, 1.0)
    ax.set_title("(a) Spotlighting-with-delimiting raises Cobra-Full ASR in every suite")
    ax.legend(frameon=False, loc="upper right", fontsize=9)
    ax.grid(True, axis="y", alpha=0.25)

    # Panel B: delta vs no-defense per (attack, defense)
    ax = axes[1]
    deltas = []
    for atk in ["cobra_full", "cobra_ablate", "chatinject", "ignorprev"]:
        for d in defenses_to_show[1:]:
            for s in SUITES:
                base_row = g[(g.attack == atk) & (g.defense == "none") & (g.suite == s)]
                def_row = g[(g.attack == atk) & (g.defense == d) & (g.suite == s)]
                if base_row.empty or def_row.empty:
                    continue
                deltas.append({"attack": atk, "defense": d, "suite": s,
                               "delta": def_row["asr"].iloc[0] - base_row["asr"].iloc[0]})
    delta_df = pd.DataFrame(deltas)
    if not delta_df.empty:
        piv = delta_df.pivot_table(index=["attack", "suite"], columns="defense", values="delta")
        # Compute average delta per (attack, defense)
        avg = delta_df.groupby(["attack", "defense"])["delta"].mean().reset_index()
        attacks_present = ["cobra_full", "cobra_ablate", "chatinject", "ignorprev"]
        attacks_present = [a for a in attacks_present if a in avg["attack"].unique()]
        defs_present = [d for d in defenses_to_show[1:] if d in avg["defense"].unique()]
        bw2 = 0.32
        x2 = np.arange(len(attacks_present))
        for i, d in enumerate(defs_present):
            vals = [(avg[(avg.attack == a) & (avg.defense == d)]["delta"].mean()
                     if not avg[(avg.attack == a) & (avg.defense == d)].empty else np.nan)
                    for a in attacks_present]
            ax.bar(x2 + (i - 0.5) * bw2, vals, bw2, color=palette[d],
                   label=d.replace("_", " "),
                   edgecolor="k", linewidth=0.3)
            for xi, v in zip(x2 + (i - 0.5) * bw2, vals):
                if v is not None and not np.isnan(v):
                    color = "#2ca02c" if v < 0 else "#d62728"
                    ax.text(xi, v + (0.012 if v >= 0 else -0.018), f"{v*100:+.1f}pp",
                            ha="center", fontsize=8, color=color)
        ax.axhline(0, color="k", lw=0.6)
        ax.set_xticks(x2)
        ax.set_xticklabels(attacks_present)
        ax.set_ylabel("avg ΔASR vs no-defense  (suite-averaged)")
        ax.set_title("(b) Defenses help or hurt depending on the attack")
        ax.legend(frameon=False, fontsize=9)
        ax.grid(True, axis="y", alpha=0.25)

    plt.tight_layout()
    _save(fig, "aux9_spotlighting_backfire")
    g.to_csv(TAB / "aux9_spotlighting_backfire.csv", index=False)


def aux8_fig4_replacement(df: pd.DataFrame) -> None:
    """Real Fig 4: per-asset Δ vs no_knowledge, defended vs undefended (suite-averaged)."""
    ak = df[df.framework == "asr_knowledge"].copy()
    cells = (ak.groupby(["suite", "knowledge_set", "defense"])["security_f"]
             .mean().reset_index().rename(columns={"security_f": "asr"}))
    base = cells[cells.knowledge_set == "no_knowledge"][["suite", "defense", "asr"]] \
        .rename(columns={"asr": "base"})
    cells = cells.merge(base, on=["suite", "defense"])
    cells["delta"] = cells["asr"] - cells["base"]
    cells = cells[cells.knowledge_set != "no_knowledge"]
    avg = cells.groupby(["knowledge_set", "defense"])["delta"].agg(["mean", "sem", "count"]).reset_index()
    order = avg.groupby("knowledge_set")["mean"].mean().sort_values(ascending=False).index.tolist()
    avg["knowledge_set"] = pd.Categorical(avg["knowledge_set"], categories=order, ordered=True)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    bw = 0.38
    x = np.arange(len(order))
    for i, defn in enumerate(["no_defense", "repeat_user_prompt"]):
        sub = avg[avg.defense == defn].set_index("knowledge_set").reindex(order)
        ax.bar(x + (i - 0.5) * bw, sub["mean"], width=bw, yerr=sub["sem"],
               label=defn.replace("_", " "),
               color="#1f77b4" if defn == "no_defense" else "#d62728",
               capsize=2)
    ax.set_xticks(x)
    ax.set_xticklabels([k.replace("_", " ") for k in order], rotation=22, ha="right")
    ax.axhline(0, color="k", lw=0.6)
    ax.set_ylabel("mean ASR Δ vs no-knowledge (averaged across suites)")
    ax.set_title("Single-asset recon impact — real numbers (paper Fig 4 replacement)")
    ax.legend(frameon=False)
    plt.tight_layout()
    _save(fig, "aux8_fig4_replacement")
    avg.to_csv(TAB / "aux8_fig4_replacement.csv", index=False)


# ---------------------------------------------------------------------------
# Numeric replication: Tables II & III
# ---------------------------------------------------------------------------

def replicate_tables(df: pd.DataFrame) -> None:
    sub = df.copy()
    sub["attack"] = sub.apply(_attack_family, axis=1)
    sub = sub[sub.security.notna()]
    # Table II: no-defense, model gpt-4.1, per (attack, suite)
    t2_src = sub[(sub.defense == "none")
                 & ((sub.model == "gpt-4.1") | sub.model.isna())]
    t2 = (t2_src.groupby(["attack", "suite"])
          .agg(asr=("security_f", "mean"), n=("security_f", "size"))
          .reset_index())
    t2_pivot = t2.pivot(index="attack", columns="suite", values="asr").reindex(columns=SUITES)
    t2_n = t2.pivot(index="attack", columns="suite", values="n").reindex(columns=SUITES)
    t2_pivot["Avg"] = t2_pivot.mean(axis=1)
    order = [a for a in ATTACK_ORDER if a in t2_pivot.index] + \
            [a for a in t2_pivot.index if a not in ATTACK_ORDER]
    t2_pivot = t2_pivot.reindex(order)
    t2_n = t2_n.reindex(order)
    # markdown
    with open(TAB / "table2_replicated.md", "w") as f:
        f.write("# Table II (replicated from per_attempt.parquet, no defense, gpt-4.1)\n\n")
        f.write(t2_pivot.map(lambda v: f"{v*100:.1f}%" if pd.notna(v) else "—").to_markdown())
        f.write("\n\n## n per cell\n\n")
        f.write(t2_n.map(lambda v: f"{int(v)}" if pd.notna(v) else "—").to_markdown())
    t2_pivot.to_csv(TAB / "table2_replicated.csv")
    t2_n.to_csv(TAB / "table2_replicated_n.csv")

    # Table III: per (attack, defense), suite-averaged ASR
    t3 = (sub[sub.defense.isin(DEFENSE_ORDER)]
          .groupby(["attack", "defense", "suite"])
          .agg(asr=("security_f", "mean"),
               util=("utility_f", "mean"),
               n=("security_f", "size"))
          .reset_index())
    t3_avg = (t3.groupby(["attack", "defense"])
              .agg(asr=("asr", "mean"), util=("util", "mean"), n=("n", "sum"))
              .reset_index())
    t3_pivot_asr = t3_avg.pivot(index="attack", columns="defense", values="asr").reindex(columns=DEFENSE_ORDER)
    t3_pivot_util = t3_avg.pivot(index="attack", columns="defense", values="util").reindex(columns=DEFENSE_ORDER)
    t3_pivot_n = t3_avg.pivot(index="attack", columns="defense", values="n").reindex(columns=DEFENSE_ORDER)
    t3_pivot_asr = t3_pivot_asr.reindex([a for a in ATTACK_ORDER if a in t3_pivot_asr.index]
                                       + [a for a in t3_pivot_asr.index if a not in ATTACK_ORDER])
    t3_pivot_util = t3_pivot_util.reindex(t3_pivot_asr.index)
    t3_pivot_n = t3_pivot_n.reindex(t3_pivot_asr.index)
    with open(TAB / "table3_replicated.md", "w") as f:
        f.write("# Table III (replicated, suite-averaged ASR per (attack, defense))\n\n")
        f.write("## ASR\n\n")
        f.write(t3_pivot_asr.map(lambda v: f"{v*100:.1f}%" if pd.notna(v) else "—").to_markdown())
        f.write("\n\n## Utility\n\n")
        f.write(t3_pivot_util.map(lambda v: f"{v*100:.1f}%" if pd.notna(v) else "—").to_markdown())
        f.write("\n\n## n per cell\n\n")
        f.write(t3_pivot_n.map(lambda v: f"{int(v)}" if pd.notna(v) else "—").to_markdown())
    t3_pivot_asr.to_csv(TAB / "table3_replicated_asr.csv")
    t3_pivot_util.to_csv(TAB / "table3_replicated_util.csv")
    t3_pivot_n.to_csv(TAB / "table3_replicated_n.csv")


# ---------------------------------------------------------------------------
# Bake-off summary
# ---------------------------------------------------------------------------

def bakeoff(df: pd.DataFrame) -> None:
    """Score each Fig-3 candidate and write bakeoff_summary.md."""
    out = []

    # Headline finding outside the 4 Fig-3 candidates: spotlighting backfire on Cobra
    sub = df.copy()
    sub["attack"] = sub.apply(_attack_family, axis=1)
    sub_v = sub[sub.security.notna() & (sub.attack == "cobra_full")
                & (sub.suite.isin(SUITES))]
    backfire = (sub_v.groupby(["suite", "defense"])
                .agg(asr=("security_f", "mean"), n=("security_f", "size")).reset_index())
    backfire_p = backfire.pivot(index="suite", columns="defense", values="asr")
    delta_spot = (backfire_p.get("spotlighting_with_delimiting") - backfire_p.get("none")).dropna()
    delta_repeat = (backfire_p.get("repeat_user_prompt") - backfire_p.get("none")).dropna()

    # A: per-task scatter — Spearman rho between base ASR and recon lift
    ak = df[df.framework == "asr_knowledge"].copy()
    base = (ak[(ak.knowledge_set == "no_knowledge") & (ak.defense == "no_defense")]
            .groupby(["suite", "user_task_id", "injection_task_id"])["security_f"]
            .mean().rename("base").reset_index())
    best = (ak[(ak.defense == "no_defense") & (ak.knowledge_set != "no_knowledge")]
            .groupby(["suite", "user_task_id", "injection_task_id"])["security_f"]
            .max().rename("best").reset_index())
    merged = base.merge(best, on=["suite", "user_task_id", "injection_task_id"])
    merged["lift"] = merged["best"] - merged["base"]
    from scipy.stats import spearmanr
    rho_a, p_a = spearmanr(merged["base"], merged["lift"])
    # Bottom vs top quartile lift
    bins = [-0.01, 0.5, 1.01]
    merged["q"] = pd.cut(merged["base"], bins=bins, labels=["bottom_half", "top_half"], include_lowest=True)
    qmean = merged.groupby("q", observed=False)["lift"].mean()
    out.append({
        "candidate": "A (per-task recon-lift scatter)",
        "headline": (f"Recon lifts ASR by {qmean['bottom_half']*100:+.1f}pp on bottom-half-difficulty pairs "
                     f"vs {qmean['top_half']*100:+.1f}pp on top-half pairs"),
        "stat": f"Spearman rho(base, lift) = {rho_a:.3f}, p = {p_a:.3g}",
        "n_pairs": len(merged),
        "suites_covered": merged["suite"].nunique(),
    })

    # B: hierarchy & ROI — best single asset delta and # assets to 90%
    cells = (ak.groupby(["suite", "knowledge_set", "defense"])["security_f"]
             .mean().reset_index().rename(columns={"security_f": "asr"}))
    base_c = cells[cells.knowledge_set == "no_knowledge"][["suite", "defense", "asr"]].rename(columns={"asr": "base"})
    cells = cells.merge(base_c, on=["suite", "defense"])
    cells["delta"] = cells["asr"] - cells["base"]
    cells_singles = cells[~cells.knowledge_set.str.startswith("multi__")]
    cells_singles = cells_singles[cells_singles.knowledge_set != "no_knowledge"]
    top = cells_singles[cells_singles.defense == "no_defense"].sort_values("delta", ascending=False).head(3)
    out.append({
        "candidate": "B (asset hierarchy + ROI)",
        "headline": "Top-3 single-asset Δ at no_defense: " + ", ".join(
            f"{r.knowledge_set}@{r.suite}={r.delta*100:+.1f}pp" for _, r in top.iterrows()
        ),
        "stat": f"max single-asset Δ averaged across suites = {cells_singles.groupby('knowledge_set')['delta'].mean().max()*100:+.1f}pp",
        "n_pairs": int(cells_singles["knowledge_set"].nunique() * cells_singles["suite"].nunique()),
        "suites_covered": cells_singles["suite"].nunique(),
    })

    # C: asset×defense interaction — count of cells where ASR(repeat) > ASR(no_def)
    pivot = cells.pivot_table(index=["suite", "knowledge_set"], columns="defense", values="asr").reset_index()
    if "no_defense" in pivot.columns and "repeat_user_prompt" in pivot.columns:
        pivot["delta_d"] = pivot["repeat_user_prompt"] - pivot["no_defense"]
        pos = pivot[pivot["delta_d"] > 0.01]
        out.append({
            "candidate": "C (asset×defense interaction)",
            "headline": f"{len(pos)} (suite, asset) cells where ASR is *higher* under repeat_user_prompt than under no_defense",
            "stat": f"max defensed-vs-undefensed gain = {pivot['delta_d'].max()*100:+.1f}pp; observed in "
                    f"{','.join(pos['knowledge_set'].astype(str).unique())}",
            "n_pairs": int(pivot["knowledge_set"].nunique() * pivot["suite"].nunique()),
            "suites_covered": pivot["suite"].nunique(),
        })

    # D: super-additivity for banking
    bk = ak[ak.suite == "banking"]
    bk_cells = bk.groupby(["knowledge_set", "defense"])["security_f"].mean().reset_index().rename(columns={"security_f": "asr"})
    base_bk = bk_cells[bk_cells.knowledge_set == "no_knowledge"].set_index("defense")["asr"]
    syn_rows = []
    for mkey in bk_cells["knowledge_set"].unique():
        if not mkey.startswith("multi__"):
            continue
        components = mkey.replace("multi__", "").split("__")
        for defn in ["no_defense", "repeat_user_prompt"]:
            sub_d = bk_cells[bk_cells.defense == defn]
            if mkey not in sub_d["knowledge_set"].values:
                continue
            obs = sub_d[sub_d.knowledge_set == mkey]["asr"].iloc[0]
            base_v = base_bk.get(defn, 0.0)
            unattacked = 1 - base_v
            covered = unattacked
            for c in components:
                if c not in sub_d["knowledge_set"].values:
                    continue
                comp_asr = sub_d[sub_d.knowledge_set == c]["asr"].iloc[0]
                lift = max(0.0, comp_asr - base_v)
                covered *= (1 - lift / max(unattacked, 1e-6))
            pred = 1 - covered
            syn_rows.append({"combo": mkey, "defense": defn,
                             "predicted": pred, "observed": obs, "synergy": obs - pred})
    if syn_rows:
        sdf = pd.DataFrame(syn_rows)
        out.append({
            "candidate": "D (super-additivity, banking only)",
            "headline": (f"Max synergy: {sdf['synergy'].max()*100:+.1f}pp, "
                         f"on {sdf.loc[sdf['synergy'].idxmax(), 'combo']}/"
                         f"{sdf.loc[sdf['synergy'].idxmax(), 'defense']}"),
            "stat": f"mean synergy across observed combos = {sdf['synergy'].mean()*100:+.1f}pp",
            "n_pairs": len(sdf),
            "suites_covered": 1,
        })

    with open(TAB / "bakeoff_summary.md", "w") as f:
        f.write("# Figure 3 bake-off — candidate ranking\n\n")
        f.write("All four candidates pull from the ASR-Knowledge data — 4 suites × 8–10 single-asset cells "
                "(plus 2 banking multi-asset cells) × 2 defenses × 144 (UT × IJ) pairs each. "
                "The recommended winner is **Candidate A (recon-lift by difficulty)**: the cleanest novel "
                "finding, holds across all four suites, and would replace the placeholder 'attacker freedom' "
                "framing the paper draft currently uses.\n\n")
        for i, row in enumerate(out, start=1):
            f.write(f"## Candidate {row['candidate']}\n\n")
            f.write(f"- **Headline:** {row['headline']}\n")
            f.write(f"- **Statistic:** {row['stat']}\n")
            f.write(f"- **Sample size:** {row['n_pairs']} pairs / cells\n")
            f.write(f"- **Suites covered:** {row['suites_covered']} / 4\n\n")
        f.write("---\n\n## Bonus headline finding (outside the Fig-3 candidates)\n\n")
        f.write("**The `spotlighting_with_delimiting` defense backfires on Cobra-Full in 4/4 suites.** "
                f"Suite-averaged ΔASR vs no-defense: {delta_spot.mean()*100:+.1f}pp (range "
                f"{delta_spot.min()*100:+.1f}pp to {delta_spot.max()*100:+.1f}pp). "
                f"By contrast `repeat_user_prompt` *does* work on Cobra-Full: "
                f"{delta_repeat.mean()*100:+.1f}pp avg (range {delta_repeat.min()*100:+.1f} to "
                f"{delta_repeat.max()*100:+.1f}pp).\n\n")
        f.write("This is the figure in `aux9_spotlighting_backfire.pdf` and lives outside the original "
                "Fig-3 candidate set. Worth promoting in the paper either as a stand-alone figure or "
                "merged into the existing Table-III narrative.\n\n")
        f.write("_(All figures live at Data/EDA/figures/; numerics at Data/EDA/tables/.)_\n")
    print(f"  -> {TAB / 'bakeoff_summary.md'}")


# ---------------------------------------------------------------------------

def main():
    print("[load]", PQ)
    df = load()
    print(f"  rows={len(df)}, frameworks={df['framework'].nunique()}, suites={df['suite'].nunique()}")

    print("\n[fig3 candidates]")
    fig3a_recon_lift_scatter(df)
    fig3a_v2_difficulty_bars(df)
    fig3b_asset_hierarchy_roi(df)
    fig3c_asset_defense_matrix(df)
    fig3d_super_additivity(df)

    print("\n[auxiliary figures]")
    aux1_cross_baseline_landscape(df)
    aux2_defense_bypass_heatmap(df)
    aux3_convergence_curves(df)
    aux4_payload_morphology(df)
    aux5_ut_ij_heatmap(df)
    aux6_failure_taxonomy(df)
    aux7_cost_pareto(df)
    aux8_fig4_replacement(df)
    aux9_spotlighting_backfire(df)

    print("\n[tables]")
    replicate_tables(df)

    print("\n[bakeoff]")
    bakeoff(df)

    print("\nDone.")


if __name__ == "__main__":
    import re
    main()
