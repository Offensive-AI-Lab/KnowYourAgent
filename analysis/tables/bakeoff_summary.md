# Figure 3 bake-off — candidate ranking

All four candidates pull from the ASR-Knowledge data — 4 suites × 8–10 single-asset cells (plus 2 banking multi-asset cells) × 2 defenses × 144 (UT × IJ) pairs each. The recommended winner is **Candidate A (recon-lift by difficulty)**: the cleanest novel finding, holds across all four suites, and would replace the placeholder 'attacker freedom' framing the paper draft currently uses.

## Candidate A (per-task recon-lift scatter)

- **Headline:** Recon lifts ASR by +29.7pp on bottom-half-difficulty pairs vs -15.6pp on top-half pairs
- **Statistic:** Spearman rho(base, lift) = -0.317, p = 4e-16
- **Sample size:** 629 pairs / cells
- **Suites covered:** 4 / 4

## Candidate B (asset hierarchy + ROI)

- **Headline:** Top-3 single-asset Δ at no_defense: agent_task@workspace=+58.1pp, tool_names_and_parameters@slack=+32.4pp, agent_task@slack=+30.5pp
- **Statistic:** max single-asset Δ averaged across suites = +44.3pp
- **Sample size:** 36 pairs / cells
- **Suites covered:** 4 / 4

## Candidate C (asset×defense interaction)

- **Headline:** 1 (suite, asset) cells where ASR is *higher* under repeat_user_prompt than under no_defense
- **Statistic:** max defensed-vs-undefensed gain = +4.7pp; observed in behavioral_rules
- **Sample size:** 48 pairs / cells
- **Suites covered:** 4 / 4

## Candidate D (super-additivity, banking only)

- **Headline:** Max synergy: +10.9pp, on multi__filters__guardrails__structural_defenses/repeat_user_prompt
- **Statistic:** mean synergy across observed combos = +10.4pp
- **Sample size:** 2 pairs / cells
- **Suites covered:** 1 / 4

---

## Bonus headline finding (outside the Fig-3 candidates)

**The `spotlighting_with_delimiting` defense backfires on Cobra-Full in 4/4 suites.** Suite-averaged ΔASR vs no-defense: +14.9pp (range +3.0pp to +29.1pp). By contrast `repeat_user_prompt` *does* work on Cobra-Full: -19.4pp avg (range -35.8 to -9.6pp).

This is the figure in `aux9_spotlighting_backfire.pdf` and lives outside the original Fig-3 candidate set. Worth promoting in the paper either as a stand-alone figure or merged into the existing Table-III narrative.

_(All figures live at analysis/figures/; numerics at analysis/tables/.)_
