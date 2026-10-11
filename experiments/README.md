# `experiments/` — the paper's experiment harnesses

Drivers for the headline experiments. Each ships its **rendered result summaries** (not the
raw per-run logs, which are large and messy — regenerate them by re-running). The figures
built from these results live in [`../analysis/`](../analysis/).

| Dir | Experiment | Result |
|---|---|---|
| [`openhands_grid/`](openhands_grid/) | KYA vs OpenHands over the Table-IV grid (repos × injection goals). `results/COMBINED_SUMMARY.md` is authoritative; `eda/FINDINGS.md` is the write-up. | Table IV |
| [`asr_knowledge/`](asr_knowledge/) | Ablates each reconnaissance *knowledge asset* to measure its lift on attack-success-rate. | Figure 3 |
| [`recon_success/`](recon_success/) | Measures how reliably the Recon agent recovers each asset (`results/*/summary.json`). | recon-reliability study |

Each subdirectory has its own README with the exact commands. They import the KYA framework
and benchmark sessions from this repo, so run them from the repository root with the
project installed (`pip install -e .`).

> **OpenHands grid caveat:** repos that bind a fixed local port (e.g. `flask-blog`) cannot
> run two of their lanes at once. The grid runner serialises same-repo lanes and parallelises
> across repos; keep `--workers 1` unless you understand the locking. See
> [`openhands_grid/README.md`](openhands_grid/README.md).
