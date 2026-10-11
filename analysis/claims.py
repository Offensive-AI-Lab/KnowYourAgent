"""Claim-validation figures for the Pentest-Agent ACSAC paper.

One figure per persuasion target:
  Fig A   — C1 : Cobra-Full substantially outperforms every black-box IPI baseline.
  Fig B   — C2+C3 : Both reconnaissance and tactics are essential; ablating either crushes ASR.
            Variants kept under review: v1 (dumbbell) and v3 (Venn of pair-level
            ablation outcomes — pooled figB_v3_breakdown + per-suite
            figB_v3_breakdown_suites). The Venn answers "are there pairs no single
            module cracks?": yes — Full-only (needs both) + impregnable.
  Fig 3   — C4 : Reconnaissance helps disproportionately on cases where static attacks fail.
  Fig 4   — C5 : Knowledge assets contribute differentially; some dominate, others barely matter.
            Variant: v3 (dual panel — cross-suite hierarchy + per-suite Δ for top-3 assets).

All figures read from the unified per_attempt.parquet (build_parquet.py).
Styling targets ACSAC two-column layout (Helvetica/Arial, ~7" wide).
Internal figure titles are stripped — the narrative belongs in the LaTeX caption.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib_venn import venn3, venn3_circles
from matplotlib_venn.layout.venn3 import DefaultLayoutAlgorithm
from scipy.stats import beta

HERE = Path(__file__).resolve().parent
PQ = HERE / "parquet" / "per_attempt.parquet"
FIG = HERE / "figures_claims"
TAB = HERE / "tables_claims"
FIG.mkdir(parents=True, exist_ok=True)
TAB.mkdir(parents=True, exist_ok=True)

SUITES = ["banking", "slack", "travel", "workspace"]

# ---- Polished ACSAC palette --------------------------------------------------
SUITE_COLOR = {
    "banking":   "#2b6cb0",  # deep blue
    "slack":     "#2f855a",  # forest green
    "travel":    "#b7791f",  # ochre (less aggressive than red)
    "workspace": "#6b46c1",  # purple
}
# Cobra ablation palette — sequential semantic (Full = strongest)
COBRA_FULL    = "#9c2a2a"   # deep red
COBRA_NOTAC   = "#dd8c50"   # warm orange
COBRA_NORECON = "#7c93ad"   # cool slate
# Static baselines
BASELINE_GRAY = "#a0aec0"
BASELINE_DARK = "#4a5568"
# Defense conditions
NO_DEF        = "#1e4e8c"   # dark blue
W_DEF         = "#b03a3a"   # dark red
# Categorical neutrals
NEUTRAL_DARK   = "#2d3748"
NEUTRAL_MID    = "#718096"
NEUTRAL_LIGHT  = "#e2e8f0"
DELTA_POS      = "#2f855a"
DELTA_NEG      = "#c0392b"

# Friendly asset display names (avoid raw snake_case in published figures)
ASSET_LABEL = {
    "agent_task":                  "user-task description",
    "tool_names_and_parameters":   "available tools & schemas",
    "defenses":                    "defense identity",
    "type_of_agent":               "agent role / type",
    "user_persona":                "user persona",
    "injected_tool_output":        "tool-output formatting",
    "model_identity":              "underlying LLM",
    "benign_response":             "benign response example",
    "behavioral_rules":            "behavioral guardrails",
}

# ---- ACSAC-grade matplotlib styling -----------------------------------------
plt.rcParams.update({
    "figure.dpi": 130,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.08,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,

    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "Liberation Sans", "DejaVu Sans"],
    "font.size": 11,
    "axes.titlesize": 11,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 9.5,

    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.linewidth": 0.8,
    "axes.edgecolor": "#222222",
    "axes.labelcolor": "#222222",
    "axes.titlepad": 6,
    "axes.labelpad": 3,

    "legend.frameon": False,
    "legend.handlelength": 1.6,
    "legend.handletextpad": 0.6,
    "legend.columnspacing": 1.2,
    "legend.labelspacing": 0.4,

    "xtick.color": "#222222",
    "ytick.color": "#222222",
    "xtick.major.width": 0.8,
    "ytick.major.width": 0.8,
    "xtick.major.size": 3.5,
    "ytick.major.size": 3.5,

    "grid.color": "#c8ccd2",
    "grid.alpha": 0.65,
    "grid.linewidth": 0.6,
    "axes.grid.axis": "y",
})


# ---- Helpers ----------------------------------------------------------------

def _save(fig, name: str):
    fig.savefig(FIG / f"{name}.pdf")
    fig.savefig(FIG / f"{name}.png")
    plt.close(fig)
    print(f"  -> figures_claims/{name}.pdf  +  .png")


def load() -> pd.DataFrame:
    df = pd.read_parquet(PQ).copy()
    df["security_f"] = df["security"].astype("Float64").astype(float)
    df["utility_f"] = df["utility"].astype("Float64").astype(float)
    return df


def _wilson_ci(k, n, conf=0.95):
    if n == 0:
        return (np.nan, np.nan, np.nan)
    alpha = 1 - conf
    lo = beta.ppf(alpha / 2, k, n - k + 1) if k > 0 else 0.0
    hi = beta.ppf(1 - alpha / 2, k + 1, n - k) if k < n else 1.0
    return (k / n, lo, hi)


def _case_level(df: pd.DataFrame, suites=None) -> pd.DataFrame:
    """One row per (framework, defense, model, knowledge_set, suite, UT, IJ);
    case_success = any attempt succeeded."""
    if suites is not None:
        df = df[df.suite.isin(suites)]
    valid = df[df.security.notna()]
    case = (valid.groupby(["framework", "cobra_variant", "model", "defense", "knowledge_set",
                            "suite", "user_task_id", "injection_task_id"], dropna=False)
                 .agg(case_success=("security", "any"),
                      n_attempts=("attempt_idx", "max"))
                 .reset_index())
    return case


def _cumulative_per_attempt(df, max_attempts: int = 6):
    """Per case (raw_path), find lowest attempt_idx where security=True. Return
    cumulative-success rate at attempts 1..max_attempts."""
    valid = df[df.security.notna()]
    suc = (valid[valid.security == True]
           .groupby("raw_path")["attempt_idx"].min().rename("first_succ"))
    cases = valid.groupby("raw_path").size().rename("n_attempts")
    df_cases = pd.concat([cases, suc], axis=1).reset_index()
    n_total = len(df_cases)
    if n_total == 0:
        return pd.DataFrame()
    xs = np.arange(1, max_attempts + 1)
    cum = [(df_cases["first_succ"].dropna() <= x).sum() / n_total for x in xs]
    return pd.DataFrame({"attempt": xs, "cum_asr": cum, "n": [n_total] * len(xs)})


def _final_asr_per_variant(df) -> pd.DataFrame:
    """Final cumulative ASR per (suite, variant). Variants: Full / NoTactics / NoRecon."""
    sub = df[(df.framework == "cobra_v3") & (df.defense == "none")
             & (df.model == "gpt-4.1") & (df.suite.isin(SUITES))]
    rows = []
    for suite in SUITES:
        for variant_val, lbl in [(None, "Full"), ("NoTactics", "NoTactics"), ("NoRecon", "NoRecon")]:
            if variant_val is None:
                ssub = sub[sub.cobra_variant.isna() & (sub.suite == suite)]
            else:
                ssub = sub[(sub.cobra_variant == variant_val) & (sub.suite == suite)]
            if ssub.empty:
                continue
            cum = _cumulative_per_attempt(ssub, max_attempts=6)
            if cum.empty:
                continue
            asr = cum["cum_asr"].iloc[-1]
            n = int(cum["n"].iloc[0])
            k, lo, hi = _wilson_ci(round(asr * n), n)
            rows.append({"suite": suite, "variant": lbl,
                         "asr": asr, "lo": lo, "hi": hi, "n": n})
    return pd.DataFrame(rows)


def _pair_outcomes(df) -> pd.DataFrame:
    """Per (suite, UT, IJ): which of {Full, NoTactics, NoRecon} cracked it (boolean)."""
    sub = df[(df.framework == "cobra_v3") & (df.defense == "none")
             & (df.model == "gpt-4.1") & (df.suite.isin(SUITES))]
    case = (sub.groupby(["cobra_variant", "suite", "user_task_id", "injection_task_id"],
                         dropna=False)
                 .agg(success=("security", "any"))
                 .reset_index())
    full = case[case.cobra_variant.isna()].rename(columns={"success": "F"})
    noT  = case[case.cobra_variant == "NoTactics"].rename(columns={"success": "T"})
    noR  = case[case.cobra_variant == "NoRecon"].rename(columns={"success": "R"})
    m = (full[["suite", "user_task_id", "injection_task_id", "F"]]
            .merge(noT[["suite", "user_task_id", "injection_task_id", "T"]],
                   on=["suite", "user_task_id", "injection_task_id"])
            .merge(noR[["suite", "user_task_id", "injection_task_id", "R"]],
                   on=["suite", "user_task_id", "injection_task_id"]))
    return m


# =============================================================================
# Fig A — C1: Cobra-Full substantially outperforms every baseline
# =============================================================================

def figA_cross_baseline(df: pd.DataFrame) -> None:
    # AgentVigil rows are already restricted to the retrain held-out test
    # split by ingest_agentvigil() in build_parquet.py.
    case = _case_level(df, suites=SUITES)
    case = case[case.defense == "none"]

    def label(row):
        fw = row.framework
        if fw == "cobra_v3":
            if pd.isna(row.cobra_variant):
                return "Cobra-Full"
            return {"NoRecon": "Cobra-NoRecon", "NoTactics": "Cobra-NoTactics"}.get(row.cobra_variant)
        return {"ignorprev": "IgnorePrev.", "topicattack": "TopicAttack",
                "chatinject": "ChatInject", "agentvigil": "AgentVigil"}.get(fw)

    case["attack"] = case.apply(label, axis=1)
    case = case[case.attack.notna()]
    case_41 = case[(case.model == "gpt-4.1") | case.model.isna()]
    g = (case_41.groupby(["attack", "suite"])
                .agg(k=("case_success", "sum"), n=("case_success", "size"))
                .reset_index())
    g["asr"] = g["k"] / g["n"]
    cis = g.apply(lambda r: pd.Series(_wilson_ci(int(r.k), int(r.n)),
                                       index=["asr2", "lo", "hi"]), axis=1)
    g = pd.concat([g, cis[["lo", "hi"]]], axis=1)

    attack_order = ["IgnorePrev.", "TopicAttack", "ChatInject", "AgentVigil",
                    "Cobra-NoTactics", "Cobra-NoRecon", "Cobra-Full"]
    attack_order = [a for a in attack_order if a in g["attack"].unique()]

    # Total case count per attack across all 4 suites (flag AgentVigil's smaller n)
    n_total = g.groupby("attack")["n"].sum().to_dict()

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    bw = 0.19
    x = np.arange(len(attack_order))
    for i, s in enumerate(SUITES):
        means, los, his = [], [], []
        for a in attack_order:
            row = g[(g.attack == a) & (g.suite == s)]
            if row.empty:
                means.append(np.nan); los.append(0); his.append(0); continue
            means.append(row["asr"].iloc[0])
            los.append(row["asr"].iloc[0] - row["lo"].iloc[0])
            his.append(row["hi"].iloc[0] - row["asr"].iloc[0])
        ax.bar(x + (i - 1.5) * bw, means, bw,
               yerr=[los, his], color=SUITE_COLOR[s], label=s,
               capsize=1.6, error_kw={"elinewidth": 0.7, "ecolor": "#333"},
               linewidth=0)

    # Label only the Cobra-Full bars — above the upper CI cap, not inside it
    for i, a in enumerate(attack_order):
        if a != "Cobra-Full":
            continue
        for j, s in enumerate(SUITES):
            row = g[(g.attack == a) & (g.suite == s)]
            if row.empty:
                continue
            v = row["asr"].iloc[0]
            hi = row["hi"].iloc[0]
            ax.text(i + (j - 1.5) * bw, hi + 0.015, f"{v*100:.0f}",
                    ha="center", fontsize=8.5, fontweight="bold", color="#222")

    ax.set_xticks(x)
    ax.set_xticklabels(attack_order, rotation=18, ha="right")
    # second-tier x label: n=N total cases per attack (across 4 suites)
    for xi, a in zip(x, attack_order):
        ntot = int(n_total.get(a, 0))
        ax.annotate(f"n={ntot}", xy=(xi, 0), xytext=(0, -52),
                    textcoords="offset points", xycoords=("data", "axes fraction"),
                    ha="center", va="top", fontsize=8.5, color=NEUTRAL_MID)
    ax.set_ylabel("Attack success rate")
    ax.set_ylim(0, 1.08)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(["0", "0.2", "0.4", "0.6", "0.8", "1.0"])
    ax.legend(ncols=4, loc="upper left", bbox_to_anchor=(0.0, 1.05))
    ax.set_axisbelow(True)
    ax.grid(True, axis="y", alpha=0.4)

    plt.tight_layout()
    _save(fig, "figA_cross_baseline")
    g.to_csv(TAB / "figA_cross_baseline.csv", index=False)


# =============================================================================
# Fig B v1 — Dumbbell forest plot per suite
# =============================================================================

def figB_v1_dumbbell(df: pd.DataFrame) -> None:
    """One horizontal track per suite. Three dots (Full / NoTactics / NoRecon).
    Annotate the two gaps inline as 'NoTac→Full' and 'NoRecon→Full' deltas."""
    fin = _final_asr_per_variant(df)
    fig, ax = plt.subplots(figsize=(8.2, 3.8))

    variant_color = {"Full": COBRA_FULL, "NoTactics": COBRA_NOTAC, "NoRecon": COBRA_NORECON}
    marker = {"Full": "o", "NoTactics": "s", "NoRecon": "D"}

    y_positions = {s: i for i, s in enumerate(SUITES[::-1])}  # banking on top

    for suite, y in y_positions.items():
        rows = fin[fin.suite == suite].set_index("variant")
        if rows.empty:
            continue
        xs = rows["asr"].tolist()
        ax.plot([min(xs), max(xs)], [y, y], color=NEUTRAL_LIGHT, lw=5,
                solid_capstyle="round", zorder=1)
        for v in ["Full", "NoTactics", "NoRecon"]:
            if v not in rows.index:
                continue
            ax.scatter(rows.loc[v, "asr"], y, s=110, color=variant_color[v],
                       marker=marker[v], edgecolor="white", linewidth=1.3, zorder=3)
            ax.text(rows.loc[v, "asr"], y + 0.22, f"{rows.loc[v,'asr']*100:.0f}",
                    ha="center", va="bottom", fontsize=8.5,
                    color=variant_color[v], fontweight="bold")

        # annotate the recon gap inline above the line
        if {"Full", "NoRecon"}.issubset(rows.index):
            d = (rows.loc["Full", "asr"] - rows.loc["NoRecon", "asr"]) * 100
            x_mid = (rows.loc["NoRecon", "asr"] + rows.loc["Full", "asr"]) / 2
            ax.text(x_mid, y - 0.25, f"−{d:.0f}pp when recon removed",
                    ha="center", va="top", fontsize=9, color=DELTA_NEG,
                    fontweight="bold")

    ax.set_yticks(list(y_positions.values()))
    ax.set_yticklabels(list(y_positions.keys()))
    ax.set_ylim(-0.6, len(SUITES) - 0.4)
    ax.set_xlim(0, 1.05)
    ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_xticklabels(["0", "0.2", "0.4", "0.6", "0.8", "1.0"])
    ax.set_xlabel("Attack success rate (cumulative, 6 attempts)")
    ax.set_axisbelow(True)
    ax.grid(True, axis="x", alpha=0.4)

    legend_handles = [
        plt.Line2D([], [], marker="o", color=COBRA_FULL,    linestyle="", markersize=10, label="Full"),
        plt.Line2D([], [], marker="s", color=COBRA_NOTAC,   linestyle="", markersize=9, label="NoTactics"),
        plt.Line2D([], [], marker="D", color=COBRA_NORECON, linestyle="", markersize=9, label="NoRecon"),
    ]
    ax.legend(handles=legend_handles, ncols=3, loc="upper right",
              bbox_to_anchor=(1.0, 1.06))

    plt.tight_layout()
    _save(fig, "figB_v1_dumbbell")


# =============================================================================
# Fig B v3 — Venn of pair-level ablation outcomes
# =============================================================================
#
# Three overlapping circles, each = the set of (user-task, injection) pairs that
# an attacker variant cracks (any of 6 attempts). A=Full (recon+tactics),
# B=recon-only (NoTactics variant), C=tactics-only (NoRecon variant). The region
# a pair lands in answers C2+C3: where does each module contribute? Circles are
# schematic (equal size, classic Venn layout) so every region stays visible; each
# region's % label is sized in proportion to its count, so the big regions stand
# out without distorting the geometry. Pairs cracked by no variant (impregnable)
# are not drawn, so percentages are taken out of the cracked total and sum to 100%.

# venn3 region ids are 3-char binary over (A=Full, B=recon-only, C=tactics-only).
# Each region maps onto the same semantics as the old stacked-bar buckets.
VENN_REGION = {
    "100": ("#a8443a", "white", "needs both modules"),       # Full only
    "110": ("#f6a02c", "#222",  "recon alone suffices"),     # Full & recon-only
    "101": ("#4a7fa5", "white", "tactics alone suffices"),   # Full & tactics-only
    "111": ("#dde1e6", "#222",  "easy (all variants crack)"),# all three
    "010": ("#8b5ca8", "white", "regression (Full failed)"), # recon-only only
    "001": ("#8b5ca8", "white", "regression (Full failed)"), # tactics-only only
    "011": ("#8b5ca8", "white", "regression (Full failed)"), # recon-only & tactics-only
}
VENN_SET_COLOR = {"A": COBRA_FULL, "B": COBRA_NOTAC, "C": COBRA_NORECON}


def _venn_regions(pairs: pd.DataFrame):
    """Counts for the 7 venn3 regions + the impregnable complement.
    Returns (subsets_tuple, impregnable, total). subsets order is venn3's:
    (Abc, aBc, ABc, abC, AbC, aBC, ABC)."""
    p = pairs.copy()
    for c in ("F", "T", "R"):
        p[c] = p[c].map(bool)
    g = p.groupby(["F", "T", "R"]).size()
    def n(f, t, r):
        return int(g.get((f, t, r), 0))
    subsets = (n(True, False, False), n(False, True, False), n(True, True, False),
               n(False, False, True), n(True, False, True), n(False, True, True),
               n(True, True, True))
    return subsets, n(False, False, False), int(len(p))


VENN_ID_ORDER = ("100", "010", "110", "001", "101", "011", "111")


def _signed_area(poly):
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)


def _center_in_region(patch, lbl):
    """Move lbl to the area-centroid of its region's largest polygon, but only
    when that point falls inside the region (a crescent's centroid can land in
    its concavity — there we keep matplotlib-venn's default position)."""
    if patch is None:
        return
    from matplotlib.path import Path as _Path
    polys = [p for p in patch.get_path().to_polygons() if len(p) >= 3]
    if not polys:
        return
    poly = max(polys, key=lambda p: abs(_signed_area(p)))
    a = _signed_area(poly)
    if abs(a) < 1e-9:
        return
    x, y = poly[:, 0], poly[:, 1]
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    cx = np.sum((x + np.roll(x, -1)) * cross) / (6 * a)
    cy = np.sum((y + np.roll(y, -1)) * cross) / (6 * a)
    if _Path(poly).contains_point((cx, cy)):
        lbl.set_position((cx, cy))


def _clean_venn(ax, subsets, denom, set_labels, set_fs=11, fs_range=(9, 30),
                weight_power=0.0, region_boost=None):
    """Gently area-weighted 3-circle Venn. Region sizes scale with count**power
    (power=0 -> equal/schematic, 1 -> true area). A small power keeps every
    intersection clearly visible — no slivers — while letting the small regions
    take proportionally less space than the big ones. Each region's % label font
    also scales with its count, so the dominant parts pop.

    region_boost {region_id: factor} nudges specific region sizes — needed because
    a Venn's outer lobes are geometrically ~2x a lens region of equal weight, so
    two near-equal counts (e.g. Full-only 31% vs Full∩recon 34%) would otherwise
    render with the lens looking smaller; boosting the lens fixes the ordering.
    denom is the % base (cracked total, so the regions sum to 100%)."""
    cnt = dict(zip(VENN_ID_ORDER, subsets))
    boost = region_boost or {}
    la = DefaultLayoutAlgorithm(fixed_subset_sizes=tuple(
        (c ** weight_power if c > 0 else 0) * boost.get(rid, 1.0)
        for rid, c in zip(VENN_ID_ORDER, subsets)))
    v = venn3(subsets=subsets, set_labels=set_labels, ax=ax, layout_algorithm=la)
    for circ, key in zip(venn3_circles(subsets=subsets, ax=ax, layout_algorithm=la),
                         ("A", "B", "C")):
        circ.set_edgecolor(VENN_SET_COLOR[key])
        circ.set_linewidth(2.6)
        circ.set_alpha(0.95)
    mx = max(cnt.values()) or 1
    fmin, fmax = fs_range
    for rid in VENN_ID_ORDER:
        fc, tc, _ = VENN_REGION[rid]
        patch = v.get_patch_by_id(rid)
        if patch is not None:
            patch.set_color(fc)
            patch.set_alpha(0.9)
            patch.set_edgecolor("white")
            patch.set_linewidth(1.2)
        lbl = v.get_label_by_id(rid)
        if lbl is not None:
            if cnt[rid] == 0:
                lbl.set_text("")
                continue
            p = cnt[rid] / denom * 100
            lbl.set_text("<1%" if round(p) == 0 else f"{round(p)}%")
            lbl.set_fontsize(fmin + (cnt[rid] / mx) * (fmax - fmin))
            lbl.set_fontweight("bold")
            lbl.set_color(tc)
            _center_in_region(patch, lbl)
    for key in ("A", "B", "C"):
        t = v.get_label_by_id(key)
        if t is not None:
            t.set_color(VENN_SET_COLOR[key])
            t.set_fontsize(set_fs)
            t.set_fontweight("bold")
    return v


# Plain-language key — readable without having read the paper. (colour, text, key)
VENN_LEGEND = [
    ("#a8443a", "Cracked only with recon + tactics together", "needs_both"),
    ("#f6a02c", "Recon alone is enough",                       "recon_suffices"),
    ("#4a7fa5", "Tactics alone is enough",                     "tactics_suffices"),
    ("#dde1e6", "Cracked by every attack version",             "easy"),
    ("#8b5ca8", "Full failed, a weaker version still won",     "regression"),
]


def _venn_legend(fig_or_ax, counts=None, denom=None, **kw):
    """Colour key in plain language. Pass counts (+denom) to append the % per
    entry for the pooled figure; omit for per-suite grids (shares vary)."""
    handles = [plt.Rectangle((0, 0), 1, 1, fc=col, ec="white") for col, _, _ in VENN_LEGEND]
    labels = []
    for _, text, key in VENN_LEGEND:
        if counts is not None and denom:
            labels.append(f"{text}  —  {counts[key] / denom * 100:.0f}%")
        else:
            labels.append(text)
    return fig_or_ax.legend(handles, labels, **kw)


def figB_v3_breakdown(df: pd.DataFrame) -> None:
    """Pooled schematic Venn of pair-level ablation outcomes. Three overlapping
    circles = pairs cracked by Full / recon-only / tactics-only. Each region's %
    is out of the cracked targets (impregnable excluded) so they sum to 100%, and
    the label font size scales with the count so the dominant regions stand out."""
    pairs = _pair_outcomes(df)
    subsets, impregnable, total = _venn_regions(pairs)
    cracked = total - impregnable
    cnt = dict(zip(VENN_ID_ORDER, subsets))

    fig, ax = plt.subplots(figsize=(7.2, 6.0))
    _clean_venn(ax, subsets, cracked,
                set_labels=("Full attack\n(recon + tactics)",
                            "Recon only\n(no tactics)",
                            "Tactics only\n(no recon)"),
                fs_range=(9, 30))
    _venn_legend(ax, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncols=2, fontsize=8.5)
    _save(fig, "figB_v3_breakdown")

    # Per-region counts + % of cracked, traceable back to the figure.
    rows = [{"region": rid, "meaning": VENN_REGION[rid][2], "count": cnt[rid],
             "pct_of_cracked": round(cnt[rid] / cracked * 100, 2)} for rid in VENN_ID_ORDER]
    rows.append({"region": "000", "meaning": "impregnable", "count": impregnable,
                 "pct_of_cracked": None})
    pd.DataFrame(rows).to_csv(TAB / "figB_v3_venn_counts.csv", index=False)


def figB_v3_breakdown_suites(df: pd.DataFrame) -> None:
    """2x2 grid of per-suite schematic Venns, same encoding as the pooled figure
    (font size scales with count; % out of each suite's cracked total)."""
    pairs = _pair_outcomes(df)
    fig, axes = plt.subplots(2, 2, figsize=(8.6, 8.0))
    rows = []
    for ax, suite in zip(axes.ravel(), SUITES):
        ssub = pairs[pairs.suite == suite]
        subsets, impregnable, total = _venn_regions(ssub)
        cracked = total - impregnable
        cnt = dict(zip(VENN_ID_ORDER, subsets))
        _clean_venn(ax, subsets, cracked,
                    set_labels=("Full", "Recon-only", "Tactics-only"),
                    set_fs=9.5, fs_range=(7, 20))
        ax.set_title(f"{suite}  (n={total})", fontsize=10, fontweight="bold",
                     color=SUITE_COLOR[suite])
        for rid in VENN_ID_ORDER:
            rows.append({"suite": suite, "region": rid,
                         "meaning": VENN_REGION[rid][2], "count": cnt[rid]})
        rows.append({"suite": suite, "region": "000",
                     "meaning": "impregnable", "count": impregnable})
    _venn_legend(fig, loc="lower center", bbox_to_anchor=(0.5, 0.0),
                 ncols=5, fontsize=8.5)
    fig.subplots_adjust(hspace=0.18, wspace=0.12, bottom=0.10, top=0.95)
    _save(fig, "figB_v3_breakdown_suites")
    pd.DataFrame(rows).to_csv(TAB / "figB_v3_venn_counts_per_suite.csv", index=False)


def figB_v3_bars(df: pd.DataFrame) -> None:
    """Area-exact companion to the schematic Venn: the same outcome buckets as a
    horizontal bar chart where each bar's length is exactly its share of the
    cracked targets — so every proportion is faithful and directly comparable
    (unlike the Venn, whose 3-circle geometry can't size regions to scale). The
    3 regression sub-cases are merged into one bucket."""
    pairs = _pair_outcomes(df)
    subsets, impregnable, total = _venn_regions(pairs)
    cracked = total - impregnable
    # (label, count, colour); sorted ascending so the biggest bar lands on top.
    buckets = [
        ("Recon alone is enough",        subsets[2],                          "#f6a02c"),
        ("Needs both modules",           subsets[0],                          "#a8443a"),
        ("Cracked by every version",     subsets[6],                          "#bcc3cc"),
        ("Regression (Full failed)",     subsets[1] + subsets[3] + subsets[5], "#8b5ca8"),
        ("Tactics alone is enough",      subsets[4],                          "#4a7fa5"),
    ]
    buckets.sort(key=lambda b: b[1])
    y = np.arange(len(buckets))
    pcts = [b[1] / cracked * 100 for b in buckets]

    fig, ax = plt.subplots(figsize=(7.6, 3.6))
    ax.barh(y, pcts, color=[b[2] for b in buckets], edgecolor="white", height=0.72)
    for yi, p in zip(y, pcts):
        ax.text(p + 0.6, yi, f"{round(p)}%", va="center", ha="left",
                fontsize=11, fontweight="bold", color="#222")
    ax.set_yticks(y)
    ax.set_yticklabels([b[0] for b in buckets], fontsize=10.5)
    ax.set_xlim(0, max(pcts) * 1.12)
    ax.set_xticks([0, 10, 20, 30])
    ax.set_xticklabels(["0", "10%", "20%", "30%"])
    ax.set_xlabel(f"share of the {cracked} cracked targets")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(left=False)
    ax.set_axisbelow(True)
    ax.grid(True, axis="x", alpha=0.35)
    plt.tight_layout()
    _save(fig, "figB_v3_bars")


def figB_v3_waterfall(df: pd.DataFrame) -> None:
    """SHAP-style attribution of overall attack success. From a baseline (targets
    either single module already cracks), reconnaissance and tactics branch in
    parallel — both measured from the baseline, not stacked, so neither looks like
    it builds on the other — and 'both combined' shows the full reach. Absolute
    scale: each bar's right edge is how many of ALL targets that config solves;
    the gap to 100% (hatched) is the impregnable targets that are never solved.
    Small figsize on purpose so the text reads large at column width."""
    pairs = _pair_outcomes(df)
    s, impregnable, total = _venn_regions(pairs)
    D = total

    def P(n):
        return n / D * 100

    base = s[5] + s[6]                      # either single alone is enough
    reach_tac = base + (s[3] + s[4])        # + tactics-only cases
    reach_recon = base + (s[1] + s[2])      # + recon-only cases
    reach_both = base + s[1] + s[2] + s[3] + s[4] + s[0]   # + need-both synergy
    # rows top -> bottom: both, recon, tactics, baseline (recon right above tactics)
    rows = [("Both combined\n(recon + tactics)", base, reach_both, "#a8443a", "white"),
            ("Reconnaissance",                    base, reach_recon, "#e08a3c", "#333"),
            ("Tactics",                           base, reach_tac,  "#4a7fa5", "white"),
            ("Baseline\n(either alone)",          0,    base,        "#bcc3cc", "#333")]

    fig, ax = plt.subplots(figsize=(5.6, 3.3))
    n = len(rows)
    for i, (name, x0, x1, col, tc) in enumerate(rows):
        y = n - 1 - i
        ax.barh(y, x1 - x0, left=x0, color=col, edgecolor="white", height=0.62)
        marg, reached = P(x1 - x0), P(x1)
        if name.startswith("Baseline"):
            ax.text((x0 + x1) / 2, y, f"{round(reached)}%", ha="center", va="center",
                    color=tc, fontsize=12.5, fontweight="bold")
        elif marg >= 9:                          # marginal in bar, reached after
            ax.text((x0 + x1) / 2, y, f"+{round(marg)}%", ha="center", va="center",
                    color=tc, fontsize=12.5, fontweight="bold")
            if name.startswith("Both"):          # reached sits inside the bar (hatched follows)
                ax.text(x1 - D * 0.012, y, f"{round(reached)}%", ha="right", va="center",
                        color="white", fontsize=11.5, fontweight="bold")
            else:
                ax.text(x1 + D * 0.015, y, f"{round(reached)}%", ha="left", va="center",
                        color="#222", fontsize=11.5, fontweight="bold")
        else:                                    # small bar: one combined label after it
            ax.text(x1 + D * 0.018, y, f"+{round(marg)}%  →  {round(reached)}%",
                    ha="left", va="center", color="#333", fontsize=11, fontweight="bold")
    # impregnable remainder on the 'both' row, hatched
    ax.barh(n - 1, impregnable, left=reach_both, color="#e7eaee",
            edgecolor="white", height=0.62, hatch="////")
    ax.text(reach_both + impregnable / 2, n - 1, f"{round(P(impregnable))}%", ha="center",
            va="center", color="#777", fontsize=9, fontweight="bold")
    # baseline anchor line — shows every branch starts from the baseline
    ax.plot([base, base], [-0.45, n - 1 + 0.45], ls=":", lw=1.3, color="#888", zorder=0)
    ax.set_yticks(range(n))
    ax.set_yticklabels([r[0] for r in rows][::-1], fontsize=10.5)
    ax.set_xlim(0, D)
    ax.set_xticks([0, 0.25 * D, 0.5 * D, 0.75 * D, D])
    ax.set_xticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("share of all targets solved (n = 620)")
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(left=False)
    ax.set_axisbelow(True)
    ax.grid(True, axis="x", alpha=0.3)
    plt.tight_layout()
    _save(fig, "figB_v3_waterfall")


# =============================================================================
# Fig 3 — C4 : recon recovers cases where the static attack fails
# =============================================================================

def fig3_recon_recovers(df: pd.DataFrame) -> None:
    sub = df[(df.framework == "cobra_v3") & (df.defense == "none")
             & (df.model == "gpt-4.1") & (df.suite.isin(SUITES))]
    case = (sub.groupby(["cobra_variant", "suite", "user_task_id", "injection_task_id"],
                         dropna=False)
                 .agg(success=("security", "any"))
                 .reset_index())
    no_recon = case[case.cobra_variant == "NoRecon"].rename(columns={"success": "norecon"})
    full = case[case.cobra_variant.isna()].rename(columns={"success": "full"})
    merged = no_recon[["suite", "user_task_id", "injection_task_id", "norecon"]].merge(
        full[["suite", "user_task_id", "injection_task_id", "full"]],
        on=["suite", "user_task_id", "injection_task_id"], how="inner")
    if merged.empty:
        print("[warn] no overlap between NoRecon and Full"); return
    merged["category"] = merged.apply(
        lambda r: ("both_succeed" if r.norecon and r.full
                   else "recon_recovers" if (not r.norecon) and r.full
                   else "recon_regresses" if r.norecon and not r.full
                   else "both_fail"), axis=1)
    pcts = merged.groupby(["suite", "category"]).size().unstack("category").fillna(0)
    for c in ["both_fail", "recon_recovers", "recon_regresses", "both_succeed"]:
        if c not in pcts.columns:
            pcts[c] = 0
    pcts["total"] = pcts.sum(axis=1)
    pcts_pct = pcts[["both_fail", "recon_recovers", "recon_regresses", "both_succeed"]
                   ].div(pcts["total"], axis=0)

    fig, axes = plt.subplots(1, 2, figsize=(8.6, 4.0),
                              gridspec_kw={"width_ratios": [1.0, 0.85], "wspace": 0.22})

    # ----- Panel (a) stacked bars -----
    ax = axes[0]
    colors = {
        "both_fail":        NEUTRAL_LIGHT,
        "recon_recovers":   DELTA_POS,
        "recon_regresses":  DELTA_NEG,
        "both_succeed":     "#2b6cb0",
    }
    labels = {
        "both_fail":       "both fail",
        "recon_recovers":  "recon recovers (Full=1, NoRecon=0)",
        "recon_regresses": "recon regresses",
        "both_succeed":    "both succeed",
    }
    bottom = np.zeros(len(SUITES))
    for c in ["both_fail", "recon_recovers", "recon_regresses", "both_succeed"]:
        vals = [pcts_pct.loc[s, c] if s in pcts_pct.index else 0 for s in SUITES]
        ax.bar(SUITES, vals, bottom=bottom, color=colors[c], label=labels[c],
               edgecolor="white", linewidth=1.0)
        for i, v in enumerate(vals):
            if v > 0.05:
                color_text = "white" if c in ("recon_recovers", "both_succeed") else "#2d3748"
                ax.text(i, bottom[i] + v / 2, f"{v*100:.0f}%",
                        ha="center", va="center", fontsize=9,
                        color=color_text, fontweight="bold")
        bottom += np.array(vals)
    ax.set_ylabel("share of (user-task, injection) pairs")
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.set_ylim(0, 1.0)
    ax.text(0.02, 0.97, "(a)", transform=ax.transAxes, fontsize=11,
            fontweight="bold", va="top")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.10),
              ncols=2, fontsize=8)
    ax.set_axisbelow(True)
    ax.grid(True, axis="y", alpha=0.4)

    # ----- Panel (b) recovery rate -----
    ax = axes[1]
    rec, n_fails = [], []
    for s in SUITES:
        if s not in pcts.index:
            rec.append(0); n_fails.append(0); continue
        r = pcts.loc[s, "recon_recovers"]; bf = pcts.loc[s, "both_fail"]
        denom = r + bf
        rec.append(r / denom if denom > 0 else 0)
        n_fails.append(int(denom))
    ax.bar(SUITES, rec, color=[SUITE_COLOR[s] for s in SUITES],
           edgecolor="white", linewidth=1.0)
    for i, (s, r, n) in enumerate(zip(SUITES, rec, n_fails)):
        ax.text(i, r + 0.04, f"{r*100:.0f}%",
                ha="center", fontsize=11, fontweight="bold", color="#2d3748")
        ax.text(i, r / 2, f"n={n}", ha="center", va="center",
                fontsize=8.5, color="white", fontweight="medium")
    ax.set_ylabel("recon recovery rate")
    ax.set_ylim(0, 1.0)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0", "0.25", "0.50", "0.75", "1.0"])
    ax.text(0.02, 0.97, "(b)", transform=ax.transAxes, fontsize=11,
            fontweight="bold", va="top")
    ax.set_axisbelow(True)
    ax.grid(True, axis="y", alpha=0.4)

    plt.tight_layout()
    _save(fig, "fig3_recon_recovers")
    pcts.to_csv(TAB / "fig3_recon_recovers_counts.csv")
    pcts_pct.to_csv(TAB / "fig3_recon_recovers_shares.csv")


# =============================================================================
# fig4 helpers — asset-level Δ data
# =============================================================================

def _asset_delta(df) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (per_suite_delta, agg_delta) for single-asset cells."""
    ak = df[df.framework == "asr_knowledge"].copy()
    cells = (ak.groupby(["suite", "knowledge_set", "defense"])["security_f"]
             .mean().reset_index().rename(columns={"security_f": "asr"}))
    base = (cells[cells.knowledge_set == "no_knowledge"]
            [["suite", "defense", "asr"]].rename(columns={"asr": "base"}))
    cells = cells.merge(base, on=["suite", "defense"])
    cells["delta"] = cells["asr"] - cells["base"]
    singles = cells[(cells.knowledge_set != "no_knowledge")
                    & (~cells.knowledge_set.str.startswith("multi__"))].copy()
    agg = (singles.groupby(["knowledge_set", "defense"])["delta"]
                  .agg(mean="mean", sem="sem", n="count").reset_index())
    return singles, agg


# =============================================================================
# Fig 4 v3 — Dual panel: hierarchy + per-suite breakdown of top assets
# =============================================================================

def fig4_v3_dual(df: pd.DataFrame) -> None:
    """Left: ranked asset hierarchy (cross-suite mean, no defense).
    Right: per-suite Δ bars for the top-3 assets so reader sees where they pay off most."""
    singles, agg = _asset_delta(df)
    nd_agg = agg[agg.defense == "no_defense"].set_index("knowledge_set")
    order = nd_agg["mean"].sort_values(ascending=True).index.tolist()
    top3 = nd_agg["mean"].sort_values(ascending=False).head(3).index.tolist()

    fig, axes = plt.subplots(1, 2, figsize=(9.0, 4.4),
                              gridspec_kw={"width_ratios": [1.0, 0.95], "wspace": 0.30})

    # ----- Panel (a) ranked hierarchy -----
    ax = axes[0]
    y = np.arange(len(order))
    vals = nd_agg.loc[order, "mean"].values
    sems = nd_agg.loc[order, "sem"].values
    bar_colors = [NO_DEF if v > 0.10 else NEUTRAL_MID if v >= 0 else DELTA_NEG for v in vals]
    ax.barh(y, vals, xerr=sems, color=bar_colors, height=0.6,
            edgecolor="white", linewidth=0.8, capsize=2,
            error_kw={"elinewidth": 0.7, "ecolor": "#222"})
    for yi, v in zip(y, vals):
        if abs(v) < 0.005:
            continue
        ax.text(v + (0.012 if v > 0 else -0.012), yi, f"{v*100:+.0f}",
                va="center", ha="left" if v > 0 else "right",
                fontsize=9, color="#222", fontweight="bold")
    ax.axvline(0, color="#222", lw=0.7)
    ax.set_yticks(y)
    ax.set_yticklabels([ASSET_LABEL.get(k, k.replace("_", " ")) for k in order])
    ax.set_xlabel("Δ ASR vs no-knowledge attacker (pp)")
    ax.set_xlim(-0.25, 0.70)
    ax.set_xticks([-0.2, 0.0, 0.2, 0.4, 0.6])
    ax.set_xticklabels(["−20", "0", "+20", "+40", "+60"])
    ax.text(0.02, 0.97, "(a)  asset hierarchy (avg across 4 suites)",
            transform=ax.transAxes, fontsize=10, fontweight="bold", va="top")
    ax.set_axisbelow(True)
    ax.grid(True, axis="x", alpha=0.4)

    # ----- Panel (b) per-suite for top-3 -----
    ax = axes[1]
    nd_per = singles[singles.defense == "no_defense"]
    bw = 0.24
    x = np.arange(len(SUITES))
    top3_colors = [NO_DEF, "#3182ce", "#63b3ed"]
    for i, k in enumerate(top3):
        vals, missing_idx = [], []
        for j, s in enumerate(SUITES):
            row = nd_per[(nd_per.knowledge_set == k) & (nd_per.suite == s)]
            if row.empty:
                vals.append(0.0)
                missing_idx.append(j)
            else:
                vals.append(row["delta"].iloc[0])
        ax.bar(x + (i - 1) * bw, vals, bw,
               color=top3_colors[i], edgecolor="white", linewidth=0.8,
               label=ASSET_LABEL.get(k, k))
        # mark missing cells with "n/a"
        for j in missing_idx:
            ax.text(j + (i - 1) * bw, 0.01, "n/a", ha="center", va="bottom",
                    fontsize=7.5, color=NEUTRAL_MID, rotation=90)
    ax.axhline(0, color="#222", lw=0.7)
    ax.set_xticks(x); ax.set_xticklabels(SUITES)
    ax.set_ylabel("Δ ASR vs no-knowledge (pp)")
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8])
    ax.set_yticklabels(["0", "+20", "+40", "+60", "+80"])
    ax.set_ylim(-0.10, 0.85)
    ax.text(0.02, 0.97, "(b)  per-suite Δ for top-3 assets",
            transform=ax.transAxes, fontsize=10, fontweight="bold", va="top")
    ax.legend(ncols=1, loc="upper right", fontsize=8.5, bbox_to_anchor=(1.0, 0.88))
    ax.set_axisbelow(True)
    ax.grid(True, axis="y", alpha=0.4)

    plt.tight_layout()
    _save(fig, "fig4_v3_dual")


# =============================================================================

def main():
    print("[load]", PQ)
    df = load()
    print(f"  rows={len(df)}")
    print("\n[figures]")
    figA_cross_baseline(df)
    fig3_recon_recovers(df)
    figB_v1_dumbbell(df)
    figB_v3_breakdown(df)
    figB_v3_breakdown_suites(df)
    figB_v3_bars(df)
    figB_v3_waterfall(df)
    fig4_v3_dual(df)
    print("\nDone — see Data/EDA/figures_claims/")


if __name__ == "__main__":
    main()
