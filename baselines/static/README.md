# Static baselines

Fixed-template and scripted injection attacks — no per-target optimization.

## ChatInject — `chatinject/` + `chatinject_runs/`
Multi-turn rapport-building dialogues that end in the malicious instruction, against
AgentDojo. Driver + aggregators:

```bash
python -m baselines.static.chatinject_runs.run_chatinject \
    --suite banking --model gpt-4.1-2025-04-14 --output-dir runs/chatinject/logs/banking
python -m baselines.static.chatinject_runs.aggregate_results         # Table II (no defense)
python -m baselines.static.chatinject_runs.aggregate_with_defenses   # Table III (all defenses)
```
`--defense {transformers_pi_detector,repeat_user_prompt,spotlighting_with_delimiting}`
selects a defense. `chatinject/data/` holds the dialogue sets (21 published + 6 generated
for Workspace + 62 for InjecAgent); `verify.py` checks the payload reproduction.

## Ignore-Previous / Important-Instructions — `injecagent_static/`
The classic fixed-template attacks, run against InjecAgent:

```bash
bash baselines/static/injecagent_static/run.sh --model-type GPT --model-name gpt-4.1-2025-04-14
```
