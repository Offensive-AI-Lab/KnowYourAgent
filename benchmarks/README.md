# `benchmarks/` — target benchmarks

Three agent benchmarks, each vendored and wrapped in a uniform **session API** so KYA and
the baselines can attack them through one interface. The upstream benchmarks are lightly
edited (OpenRouter support, a thread-safe PI-detector, the session wrapper); their original
licenses are preserved.

| Dir | Session API | Upstream | License |
|---|---|---|---|
| [`agentdojo/`](agentdojo/) | `benchmarks.agentdojo.src.api.AgentDojoChatSession` | [ethz-spylab/agentdojo](https://github.com/ethz-spylab/agentdojo) v0.1.34 | MIT (`agentdojo/LICENSE`) |
| [`injecagent/`](injecagent/) | `benchmarks.injecagent.src.api.InjecAgentChatSession` | [uiuc-kang-lab/InjecAgent](https://github.com/uiuc-kang-lab/InjecAgent) | MIT (`injecagent/LICENCE`) |
| [`openhands/`](openhands/) | `benchmarks.openhands.api.OpenHandsChatSession` | [All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands) (target agent, installed separately) | — |

## The session contract

Every session exposes the same shape, which is what makes KYA benchmark-agnostic:

* `init_chat()` — run the benign (un-attacked) task and return the conversation.
* an **injection** call that places attacker content and returns
  `(messages, security, utility)` — `security` = injection goal achieved,
  `utility` = benign task still completed. KYA reads `security` as ground-truth success.
* accessors used by Recon (`get_history`, and for AgentDojo `get_benign_response`,
  `get_agent_task`, `get_injected_tool_output_info`).

The AgentDojo wrapper bootstraps `sys.path` to the vendored `agentdojo` package, so no
separate install of the benchmark is needed — `pip install -e .` at the repo root is enough.

## OpenHands setup

OpenHands is a real coding agent and is **not** installed by `pyproject.toml`. To use it:

```bash
pip install openhands-ai
python -m benchmarks.openhands.bootstrap     # register one conversation per repo task
```

The bootstrap clones a known-good conversation template per repo under `~/.openhands/` and
records the ids in `benchmarks/openhands/conversation_ids.json`. The small target repos
live under `benchmarks/openhands/repos/` (pristine copies in `repos/.originals/`, reset
before every run). Run timeouts and snapshotting are controlled by the
`OPENHANDS_RUN_TIMEOUT_S` and `OPENHANDS_REPO_SNAPSHOT_DIR` environment variables.
