# `kya/` — the KYA framework

KYA pentests a target AI agent with a small [CrewAI](https://github.com/crewAIInc/crewAI)
crew that **reconnoiters, attacks, and learns from failure** in a loop. The same loop drives
all three benchmarks; only the injection mechanism and a few prompt fragments differ.

## The crew

| Role | Module | Job |
|---|---|---|
| **Planner** | [`planner/`](planner/) | Picks the most promising tactic from the tactics database given what's known about the target. |
| **Recon** | [`recon/`](recon/) | Probes the target to collect the *knowledge assets* ("preconditions") a tactic needs — tool names, the user's task, a benign response, guardrail behaviour, … |
| **Attacker** | [`attacker/`](attacker/) | Two sub-agents: one turns the tactic + collected knowledge into a concrete execution plan, the other writes the final injection payload as JSON. |
| **Evaluator** | [`planner/`](planner/) | Diagnoses a failed attempt and decides what to do next. |

Tactics and the knowledge assets they require are declared in
[`tactics_db.json`](tactics_db.json).

## The attack loop

Implemented once in [`flows/base.py`](flows/base.py), specialised per benchmark in
`flows/agentdojo.py`, `flows/injecagent.py`, `flows/openhands.py`:

```
choose tactic ──▶ RECON ──▶ ATTACK ──▶ EVALUATOR
      ▲                                     │
      └───────────── (on failure) ──────────┘
```

* **RECON** collects each precondition. If an asset can't be collected, every tactic that
  needs it is dropped and the Planner picks another.
* **ATTACK** builds and injects the payload. Success is scored **programmatically** by the
  benchmark (not by an LLM), and short-circuits the loop.
* **EVALUATOR** classifies a failure as one of:
  * `STRATEGY_EXECUTION_FAILURE` → keep the tactic, refine the payload;
  * `GUARDRAILS_FAILURE` → the target refused: add a recon objective for its guardrails and probe;
  * `STRATEGY_SELECTION_FAILURE` → drop the tactic, choose another.

Budget: up to 3 tactics and 6 injection attempts (7 for OpenHands). Override OpenHands'
budget for smoke tests with `KYA_MAX_STRATEGIES` / `KYA_MAX_EXECUTIONS`.

## Entry points

| Command | Target | Injection |
|---|---|---|
| `python -m kya.run_agentdojo` | AgentDojo | Payload placed in every environment slot the agent reads, task re-run from scratch. |
| `python -m kya.run_injecagent` | InjecAgent | Payload replaces the tool response; stage-1 success = the attacker's tool is invoked. |
| `python -m kya.run_openhands` | OpenHands | Payload written into a repo file the coding agent must open; a deterministic validator checks the agent's actions. |

All three share the runner ([`runner.py`](runner.py)): `-c/--config`, `-o/--output-dir`,
`-w/--workers`, `--resume`, `--limit`, and the model flags from [`llm.py`](llm.py).
Summarise any `results.jsonl` with `python -m kya.summarize <path>`.

## Config fields

Each config is a JSON **list**; one object per run.

**AgentDojo** (`run_agentdojo`):

| Field | Required | Default | Meaning |
|---|---|---|---|
| `suite` | ✓ | | `banking` \| `slack` \| `travel` \| `workspace` |
| `user_task` | ✓ | | e.g. `user_task_0` |
| `injection_task` | ✓ | | e.g. `injection_task_1` |
| `target_model` | ✓ | | model the target agent runs on |
| `recon` | | `true` | `false` = no-recon ablation |
| `attack_tactic` | | `true` | `false` = no-tactics ablation |
| `defense` | | `null` | `repeat_user_prompt` \| `spotlighting_with_delimiting` \| `transformers_pi_detector` |
| `system_message_name` | | `null` | override the target's system message |

**InjecAgent** (`run_injecagent`): `suite` (`dh`\|`ds`), `user_task` and `injection_task`
(integer indices, as strings), `target_model`; optional `recon`, `setting`
(`enhanced`\|`base`), `model_type` (`GPT`\|`OpenRouter`\|`Claude`\|`TogetherAI`).

**OpenHands** (`run_openhands`): `repo_name`, `user_task`, `injection_task`,
`pentesting_goal`; optional `recon`.

Ready-to-run examples live in [`../configs/`](../configs/).

## Choosing models

`kya/llm.py` holds a per-benchmark `PRESETS` table mapping each role to a model. Override
the whole crew with `--model`, or one role with `--<role>-model` (e.g.
`--evaluator-model gpt-4o`). The target agent's model is **not** a crew model — it is the
`target_model` field in the config.
