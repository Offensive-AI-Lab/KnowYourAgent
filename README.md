# KYA — Know Your Agent

Companion code for the paper **_Pentesting AI Agents_**.

KYA is a reconnaissance-driven, adaptive **multi-agent pentester** for AI agents.
Given a target agent and an attacker goal, a small CrewAI crew (Planner → Recon →
Attacker → Evaluator) iteratively **reconnoiters** the target, **chooses a tactic**,
**crafts an indirect-prompt-injection payload**, and **learns from failures** until it
either succeeds or exhausts its budget. KYA is evaluated against three benchmarks —
[AgentDojo](https://github.com/ethz-spylab/agentdojo),
[InjecAgent](https://github.com/uiuc-kang-lab/InjecAgent), and
[OpenHands](https://github.com/All-Hands-AI/OpenHands) — and compared against four
published baselines.

> **Research / defensive use only.** This code generates prompt-injection attacks to
> *measure and harden* the robustness of AI agents in sandboxed benchmarks. Only run it
> against targets you are authorised to test.

---

## What's in here

| Path | Contents |
|---|---|
| [`kya/`](kya/) | The KYA framework: the crew (`attacker/`, `recon/`, `planner/`), the attack loop (`flows/`), the tactics database, and three entry points (`run_agentdojo.py`, `run_injecagent.py`, `run_openhands.py`). |
| [`benchmarks/`](benchmarks/) | The three target benchmarks, each wrapped in a uniform session API (`src/api.py` / `api.py`). Vendored, lightly edited; licenses preserved. |
| [`baselines/`](baselines/) | The four comparison attacks: **AgentVigil** (MCTS fuzzing), **AutoHijacker**, **TopicAttack**, and the **static / ChatInject** templates. |
| [`experiments/`](experiments/) | The paper's experiment harnesses: the **OpenHands Table-IV grid**, the **ASR-vs-knowledge ablation** (Figure 3), and the **recon-success** study. |
| [`analysis/`](analysis/) | Scripts that turn run logs into the paper's figures and tables, plus the **rendered results** (figures, tables, parquet) so they can be inspected or regenerated without re-running attacks. |
| [`configs/`](configs/) | Small ready-to-run config files (one smoke test per benchmark) to copy and scale up. |

The attack loop and how each piece fits together is documented in [`kya/README.md`](kya/README.md).

---

## Setup

**Requirements:** Python 3.11 or 3.12, and an OpenAI-compatible API key.

```bash
git clone <this-repo> kya && cd kya

# Option A — uv (recommended; reproducible)
uv venv --python 3.11 && source .venv/bin/activate
uv pip install -e .

# Option B — pip / conda
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .
```

This installs CrewAI (the KYA crew), the OpenAI/LiteLLM backends, and the benchmark and
analysis dependencies — pinned to the versions used for the paper (see `pyproject.toml`).

Then provide your key:

```bash
cp .env.example .env
# edit .env and set OPENAI_API_KEY=sk-...
```

Everything is run **from the repository root** with `python -m ...`, so the `kya`,
`benchmarks`, and `baselines` packages resolve without any `PYTHONPATH` juggling.

Optional extras:

```bash
pip install -e ".[pi-detector]"   # DeBERTa prompt-injection-detector defense (GPU recommended)
pip install -e ".[together]"      # TogetherAI-hosted target models for InjecAgent
```

---

## Quick start — run KYA

Each benchmark has one entry point. All three take `-c <config.json>` (a JSON **list** of
runs), write a readable per-run `.log`, and append one line per run to a `results.jsonl`.

### AgentDojo (banking · slack · travel · workspace)

```bash
python -m kya.run_agentdojo -c configs/agentdojo/smoke.json -o runs/agentdojo_smoke
```

### InjecAgent (`dh` = direct harm · `ds` = data stealing)

```bash
python -m kya.run_injecagent -c configs/injecagent/smoke.json -o runs/injecagent_smoke
```

### OpenHands (a coding agent on small Git repos)

OpenHands needs the `openhands` CLI installed and one conversation registered per repo
task (a one-time bootstrap).

> **`openhands-ai` requires Python ≥3.12**, which conflicts with this repo's own
> Python-3.11 venv above. Install it into a *second*, separate venv and put that venv's
> `bin/` on `PATH` for the commands below — don't try to add it to the Python-3.11 venv.
>
> ```bash
> uv venv --python 3.12 .venv-openhands
> uv pip install --python .venv-openhands/bin/python openhands-ai
> export PATH="$PWD/.venv-openhands/bin:$PATH"   # so `openhands` and `bootstrap` can find the CLI
> ```

```bash
python -m benchmarks.openhands.bootstrap       # register conversations (writes to ~/.openhands)
python -m kya.run_openhands -c configs/openhands/smoke.json -o runs/openhands_smoke
```

`bootstrap.py` works by *cloning* an existing OpenHands conversation per repo, not by
creating one from scratch — `openhands --headless` refuses to start a new conversation
without interactive settings. If `~/.openhands/conversations/` is completely empty (a
genuinely fresh machine), first seed **one** conversation for any task by running
`openhands` interactively once against any repo under `benchmarks/openhands/repos/`;
`bootstrap.py` will then clone it as the template for the rest.

### Common options

| Flag | Meaning |
|---|---|
| `-o, --output-dir DIR` | Put all logs + `results.jsonl` under `DIR` (overrides per-entry `log_file`). |
| `-w, --workers N` | Run N pentests in parallel (one process each). Keep `1` for OpenHands — see its [README](experiments/openhands_grid/README.md). |
| `--resume` | Skip runs already recorded in `results.jsonl`. |
| `--limit N` | Only run the first N entries (smoke testing). |
| `-m, --model NAME` | Run the whole crew on one model. Omit to use the per-benchmark preset in [`kya/llm.py`](kya/llm.py). |
| `--<role>-model NAME` | Override a single role, e.g. `--recon-model gpt-5`. |

A minimal AgentDojo config entry; see [`kya/README.md`](kya/README.md) for every field
(ablations, defenses, target model):

```json
[
  {"suite": "banking", "user_task": "user_task_0", "injection_task": "injection_task_1",
   "target_model": "gpt-4.1-2025-04-14"}
]
```

### Scoring and results

A run **succeeds** when the benchmark's own programmatic check confirms the injection goal
was achieved (AgentDojo `security`, InjecAgent stage-1 tool invocation, OpenHands action
validator) — never by asking an LLM to grade itself. `results.jsonl` is one JSON object per
run; summarise attack-success-rate with:

```bash
python -m kya.summarize runs/agentdojo_smoke/results.jsonl
```

---

## Reproducing the baselines

Each baseline is self-contained under `baselines/` with its own README. In short:

```bash
# AgentVigil (MCTS template fuzzing) vs AgentDojo
python baselines/agentvigil/AgentDojo.py -c baselines/agentvigil/agentvigil_one_per_suite.json

# AutoHijacker vs AgentDojo
python baselines/autohijacker/autohijacker_agentdojo_runner.py \
    --config baselines/autohijacker/autohijacker_agentdojo_config.json --output runs/autohijacker

# ChatInject vs AgentDojo (static multi-turn dialogue baseline)
python -m baselines.static.chatinject_runs.run_chatinject \
    --suite banking --model gpt-4.1-2025-04-14 --output-dir runs/chatinject/logs/banking
```

See [`baselines/README.md`](baselines/README.md) for the full matrix (AgentDojo + InjecAgent,
all four defenses) and each attack's own documentation.

---

## Reproducing the experiments and figures

The **rendered figures and tables already ship** under `analysis/figures*/` and
`analysis/tables*/`. Because the underlying `analysis/parquet/per_attempt.parquet` is
included, you can regenerate every figure **without re-running any attack**:

```bash
python analysis/figures.py    # -> analysis/figures/  + analysis/tables/
python analysis/claims.py     # -> analysis/figures_claims/ + analysis/tables_claims/
```

Rebuilding the parquet itself (`analysis/build_parquet.py`) needs the raw per-attempt run
logs, which are **not** shipped — regenerate them by re-running the attacks above, or point
`KYA_RAW_DATA_ROOT` at your own run outputs. The experiment harnesses behind the paper's
headline results live in [`experiments/`](experiments/):

| Experiment | What it shows |
|---|---|
| [`experiments/openhands_grid/`](experiments/openhands_grid/) | KYA vs OpenHands on the Table-IV repo×injection grid. |
| [`experiments/asr_knowledge/`](experiments/asr_knowledge/) | How much each reconnaissance "knowledge asset" raises attack-success-rate (Figure 3). |
| [`experiments/recon_success/`](experiments/recon_success/) | How reliably the Recon agent recovers each asset. |

---

## Models

The target agent model is set per config entry (`target_model`). The KYA crew defaults are
per benchmark (see [`kya/llm.py`](kya/llm.py)) and overridable with `--model` /
`--<role>-model`. The paper's canonical target is `gpt-4.1-2025-04-14`; smoke tests use
`gpt-4o-mini-2024-07-18` to save cost. Non-OpenAI targets (Llama, Gemini, …) route through
OpenRouter — set `OPENROUTER_API_KEY` and use an OpenRouter model id.

---

## Citing

If you use this code, please cite our paper:
`@inproceedings{eliav2026know,
  title     = {Know Your Agent: Reconnaissance-Driven Pentesting of {AI} Agents},
  author    = {Eliav, Or Zion and Lenga, Eyal and Bernstein, Shir and Mirsky, Yisroel},
  booktitle = {Annual Computer Security Applications Conference (ACSAC)},
  year      = {2026}
}`
