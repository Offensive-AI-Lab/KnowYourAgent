# AutoHijacker

LLM-as-optimizer indirect prompt injection with a batch-trained attack memory
(Prompter → Attacker → Scorer). Full algorithm and paper mapping:
[`APPENDIX_AUTOHIJACKER_REPRODUCTION.md`](APPENDIX_AUTOHIJACKER_REPRODUCTION.md).

Run from the repository root:

```bash
# AgentDojo
python baselines/autohijacker/autohijacker_agentdojo_runner.py \
    --config baselines/autohijacker/autohijacker_agentdojo_config.json \
    --output runs/autohijacker/agentdojo.json

# InjecAgent
python baselines/autohijacker/autohijacker_injecagent_runner.py \
    --config baselines/autohijacker/autohijacker_injecagent_config.json \
    --output runs/autohijacker/injecagent.json
```

Defense variants (AgentDojo): `autohijacker_agentdojo_defense_config.json`,
`…_pidetector_config.json`, `…_repeat_config.json`. `attack_memory.json` is the trained
memory used at test time; retrain with `autohijacker_train.py`.
