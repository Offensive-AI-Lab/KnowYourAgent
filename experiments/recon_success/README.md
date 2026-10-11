# ReconSuccessExperiment

Measures how well KYA's reconnaissance module (`kya/recon/`) actually extracts the
knowledge assets ("requirements" in `kya/tactics_db.json`) it's supposed to
gather, by running recon in isolation against real AgentDojo targets and grading each
attempt with an LLM judge against programmatically-derived ground truth.

Tested requirements (a subset of the full `tactics_db.json` requirement list):
`tool_names_and_parameters`, `guardrails`, `structural_defenses`, `behavioral_rules`,
`model_identity`, `type_of_agent`.

## Why an LLM judge

There's no clean ground-truth string to diff recon's output against — the recon agent's
wording never matches the source verbatim, and some assets (`guardrails`,
`type_of_agent`) don't have a single "correct" phrasing at all. So each requirement gets
its own judge LLM call that sees both the real ground truth and the recon agent's raw
reported finding, and returns a `SUCCESS`/`FAILURE` verdict with reasoning.

## What you need to edit

**`judge_prompts.py`** — and only that file. It holds one judging-rubric string per
requirement (`JUDGE_INSTRUCTIONS[requirement_id]`). Edit the grading criteria there;
everything else (getting the right ground truth and recon output into the prompt,
enforcing the JSON output contract, parsing the response) is handled by `judge.py`.

## How a run works

For every `(case, requirement)` pair in the config:

1. **`recon_runner.py`** builds a fresh `AgentDojoChatSession` and runs KYA's real recon
   agent (`kya/recon/agents.py::Recon.recon_agent_env` +
   `kya/recon/tasks.py::Tasks.recon_task_env`, same tools/task classes production uses)
   against that one requirement's objective text from `tactics_db.json`. Each
   `(case, requirement)` run gets its own session and an empty `target_profile` — recon
   findings are **not** accumulated across requirements within a case (isolated mode),
   so results reflect each asset's extractability on its own, not compounded by whatever
   order a real attack run happened to collect things in.
2. **`ground_truth.py`** pulls the real facts out of that same session (the system
   prompt, the real tool list + JSON parameter schemas, the real active defense, the
   real target model string) — no LLM involved, no guessing.
3. **`judge.py`** sends the judge LLM your rubric (`judge_prompts.py`) plus the ground
   truth plus the recon agent's raw output plus a fixed output-format instruction, and
   parses the returned `{"verdict": ..., "reasoning": ...}`.

Results for each `(case, requirement)` are written immediately as their own JSON file
(so a long run is inspectable as it goes), and an aggregated `summary.json` with
SUCCESS-rate per requirement (and overall) is written at the end.

## Design notes (confirmed with the user up front)

- **A "case" is a `(suite, user_task)` pair.** There are only 97 unique pairs across
  AgentDojo's 4 suites (banking/slack/travel/workspace), so `sampling.py` caps a request
  for more at 97. The `injection_task` a session needs is auto-picked per case (the
  first one found where the injection vector is actually reachable).
- **`structural_defenses` runs under an active defense on purpose.** Every other
  requirement runs with no defense; `structural_defenses` runs with
  `spotlighting_with_delimiting` active (see `requirement_defenses` in the config), so
  its ground truth is "this specific defense is active" rather than a trivial "no
  defense" — otherwise that judge would never see a positive case. Override
  `requirement_defenses` in your config if you want a different defense, or none.
- **Recon runs isolated per requirement**, not accumulated the way
  `kya/flows/agentdojo.py`'s state machine does in production (where later
  requirements see earlier ones' findings as context). This trades production fidelity
  for a clean per-asset signal with no ordering confound. If you want the accumulating
  behavior later, `format_collected_information` in `recon_runner.py` is the one line
  to change.

## Config schema

```json
{
  "recon_model": "gpt-5",
  "target_model": "gpt-4.1-2025-04-14",
  "judge_model": "gpt-4.1-2025-04-14",
  "system_message_name": null,
  "requirements": ["tool_names_and_parameters", "guardrails", "structural_defenses",
                    "behavioral_rules", "model_identity", "type_of_agent"],
  "requirement_defenses": {"structural_defenses": "spotlighting_with_delimiting"},
  "output_dir": "ReconSuccessExperiment/results/run_100cases",
  "cases": [{"suite": "banking", "user_task": "user_task_3", "injection_task": "injection_task_2"}, "..."]
}
```

All fields except `cases` have defaults (see `main.py`/`sampling.py`), so a minimal
config only needs `cases`.

## Running it

This needs an environment with **both** KYA's deps (`crewai`, `langchain-openai`) **and**
AgentDojo's vendored deps (`agentdojo`'s own requirements, e.g. `anthropic`,
`docstring-parser`) importable in the same process — same as `kya/run_agentdojo.py` already
requires. On this machine that's the `py311` conda env (see
`ASR_knowledge_correlation/CLAUDE.md`); the plain root `uv` venv is currently missing
`agentdojo`'s dependencies (e.g. `anthropic`) so `uv run python ReconSuccessExperiment/main.py`
will fail at import time until that's reconciled — same pre-existing gap as
`kya/run_agentdojo.py`, not something new to this experiment.

```bash
source .venv/bin/activate  # or activate your own env

# 1. Build a case sample (writes configs/sampled_<n>.json)
python ReconSuccessExperiment/sampling.py --num-cases 100 --seed 42

# 2. Edit judge_prompts.py if you want different judging rubrics.

# 3. Run the experiment (--max-workers controls concurrency, default 8)
python ReconSuccessExperiment/main.py -c ReconSuccessExperiment/configs/sampled_97.json --max-workers 8
```

Re-running `main.py` on the same `output_dir` skips any `(case, requirement)` pair whose
JSON file already exists in `cases/` and rebuilds `summary.json` from every file present
there — so it's safe to stop and resume, or to hand-copy result files from an earlier
run into a new `output_dir` before continuing.

A tiny 2-case smoke-test config is at `configs/example.json`:

```bash
python ReconSuccessExperiment/main.py -c ReconSuccessExperiment/configs/example.json
```

## Output

```
results/<run_name>/
  cases/<suite>_<user_task>_<requirement_id>.json   # one per (case, requirement)
  summary.json                                       # SUCCESS rate per requirement + overall
  run.log                                             # full console log
```

Each per-case JSON has: `case`, `requirement`, `defense_name`, `recon_output` (the recon
agent's raw text), `ground_truth` (what was actually fed to the judge), and
`judge_verdict` (`{"verdict": "SUCCESS"|"FAILURE"|"ERROR", "reasoning": "..."}`).
