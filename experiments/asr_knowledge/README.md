# ASR–Knowledge Correlation Experiment

This experiment investigates how the amount and type of **attacker knowledge** about a target LLM agent correlates with the **Attack Success Rate (ASR)** of prompt-injection attacks. It uses the [AgentDojo](../../benchmarks/agentdojo/) benchmark as the evaluation environment.

## Overview

The workflow has two stages:

1. **Attack Generation** (`create_attacks.ipynb`) — An attacker LLM crafts prompt-injection payloads using a configurable subset of knowledge about the target agent.
2. **Attack Testing** (`test_attacks.ipynb`) — The generated payloads are injected into AgentDojo environments and evaluated for success.

By toggling which knowledge pieces the attacker has access to, you can measure how each category of information impacts the ASR.

---

## Directory Structure

```
ASR_knowledge_correlation/
├── attack_config.json          # Which knowledge pieces & triplets to use
├── attack_config.schema.json   # JSON Schema for the config file
├── attack_results.json         # Generated attack payloads (output of stage 1)
├── test_results.json           # Evaluation results (output of stage 2)
├── general_attacker.py         # Knowledge-gathering helpers & attacker LLM call
├── create_attacks.ipynb        # Notebook – Stage 1: generate attacks
├── test_attacks.ipynb          # Notebook – Stage 2: test attacks
└── runs/                       # (Optional) saved run artefacts by model name
```

---

## Prerequisites

- Python 3.10+
- The project's dependencies installed (see the root `pyproject.toml`).
- An OpenAI (or compatible) API key exported as `OPENAI_API_KEY` (used via [LiteLLM](https://docs.litellm.ai/)).
- The local `agentdojo` package available under `benchmarks/` (already part of this repo).

---

## Configuration

Edit **`attack_config.json`** to control the experiment. The file has two sections:

### `knowledge_pieces`

A mapping of knowledge categories → `true`/`false`. Only enabled categories are included in the attacker's context when generating payloads.

| Key                   | Description                                                        |
|-----------------------|--------------------------------------------------------------------|
| `operational_rules`   | System-level instructions / operational rules of the target agent. |
| `tools_information`   | Tool names, descriptions, and parameter schemas.                   |
| `tool_output`         | Raw tool output context (with injection placeholder) the target agent sees. |
| `benign_response`     | A sample benign response the agent produces for the user task.     |
| `security_guardrails` | Security guardrails or safety filters applied by the target agent. |

### `triplets`

An array of `[suite_name, injection_task_id, user_task_id]` triplets from AgentDojo. Each triplet defines one attack scenario.

Available suites: `banking`, `slack`, `travel`, `workspace`.

**Example:**

```json
{
  "knowledge_pieces": {
    "operational_rules": true,
    "tools_information": true,
    "tool_output": false,
    "benign_response": false,
    "security_guardrails": true
  },
  "triplets": [
    ["banking", "injection_task_0", "user_task_0"],
    ["slack", "injection_task_0", "user_task_1"]
  ]
}
```

The full schema is documented in `attack_config.schema.json`.

---

## Usage

### Stage 1 — Generate Attack Payloads

Open **`create_attacks.ipynb`** and run all cells. Key configuration variables are at the top of the notebook:

| Variable       | Purpose                                             | Default                |
|----------------|-----------------------------------------------------|------------------------|
| `MODEL_NAME`   | LLM used by the attacker to craft payloads          | `"gpt-4o"`            |
| `VERBOSE`      | Print full LLM prompts and responses                | `False`                |
| `CONFIG_PATH`  | Path to the attack configuration file               | `attack_config.json`   |
| `OUTPUT_PATH`  | Where to write the generated payloads               | `attack_results.json`  |

**What happens:**

1. The configuration is loaded and knowledge pieces are assembled per the flags.
2. For each triplet, the attacker LLM receives a system prompt containing the enabled knowledge, the environment data (tool output), and the malicious goal.
3. The LLM returns a raw injection payload string.
4. All payloads are saved to `attack_results.json` keyed by `"suite/injection_task/user_task"`.

### Stage 2 — Test Attack Payloads

Open **`test_attacks.ipynb`** and run all cells. Configuration variables:

| Variable              | Purpose                                            | Default               |
|-----------------------|----------------------------------------------------|-----------------------|
| `ATTACK_RESULTS_PATH` | Path to the JSON with generated payloads           | `attack_results.json` |
| `OUTPUT_PATH`         | Where to write evaluation results                  | `test_results.json`   |
| `MODEL_NAME`          | LLM used by the **target** agent                   | `"gpt-4o-2024-05-13"` |
| `VERBOSE`             | Print and log full agent conversations per attack  | `True`                |

**What happens:**

1. Each payload is injected into the corresponding AgentDojo environment.
2. The target agent processes the user task with the injected payload present.
3. Two metrics are evaluated:
   - **Security** (`true` = injection goal achieved, i.e., the attack succeeded).
   - **Utility** (`true` = the original user task was still satisfied).
4. Results are saved to `test_results.json`. When `VERBOSE` is enabled, the full conversation messages are included in the output file and printed to the console.

---

## Output Format

### `attack_results.json`

```json
{
  "banking/injection_task_0/user_task_0": "<raw injection payload string>",
  ...
}
```

### `test_results.json`

```json
{
  "banking/injection_task_0/user_task_0": {
    "payload": "<the injected payload>",
    "security": true,
    "utility": false,
    "messages": [...]   // Only present when VERBOSE=True
  },
  ...
}
```

The summary printed at the end of the testing notebook includes:

- Total attacks run
- Injection succeeded / failed counts
- Error count
- **ASR** (Attack Success Rate) = succeeded / (total − errors)

---

## Key Module: `general_attacker.py`

This module provides:

- **Knowledge gatherers** — One function per knowledge category (`gather_operational_rules`, `gather_tools_information`, `gather_tool_output`, `gather_benign_response`, `gather_security_guardrails`). Each extracts information from the AgentDojo suite at runtime.
- **`build_knowledge()`** — Assembles a formatted knowledge string from only the enabled categories.
- **`call_attacker_llm()`** — Sends the constructed prompt to any LiteLLM-compatible model and returns the raw payload.

---

## Running a Full Experiment

```bash
# 1. Configure the experiment
#    Edit attack_config.json to select knowledge pieces and triplets.

# 2. Generate attacks (run the notebook cells or via CLI)
jupyter nbconvert --to notebook --execute create_attacks.ipynb

# 3. Test attacks
jupyter nbconvert --to notebook --execute test_attacks.ipynb

# 4. Inspect results
cat test_results.json | python -m json.tool
```

To systematically sweep across knowledge configurations, modify `attack_config.json` between runs (e.g., enable one knowledge piece at a time) and save each `test_results.json` to a separate location for comparison.
