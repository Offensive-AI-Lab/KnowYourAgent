# `baselines/` — comparison attacks

The four prompt-injection attacks KYA is compared against. Each targets the same benchmark
session APIs ([`benchmarks/`](../benchmarks/)) so attack-success-rates are directly
comparable. The canonical target model for the paper is `gpt-4.1-2025-04-14`; use
`gpt-4o-mini-2024-07-18` for cheap smoke tests.

| Baseline | Idea | Dir | AgentDojo | InjecAgent |
|---|---|---|---|---|
| **AgentVigil** | MCTS black-box fuzzing of attack templates | [`agentvigil/`](agentvigil/) | ✓ | ✓ |
| **AutoHijacker** | LLM-as-optimizer, batch-trained attack memory | [`autohijacker/`](autohijacker/) | ✓ | ✓ |
| **TopicAttack** | indirect injection via gradual topic transition | [`topicattack/`](topicattack/) | ✓ | ✓ |
| **Static / ChatInject** | fixed templates (Ignore-Previous, Important-Instructions) and the ChatInject multi-turn dialogue attack | [`static/`](static/) | ✓ | ✓ |

## AgentVigil — [`agentvigil/`](agentvigil/README.md)

MCTS fuzzer that mutates a pool of attack templates and keeps the best.

```bash
# smoke: one case per suite
python baselines/agentvigil/AgentDojo.py -c baselines/agentvigil/agentvigil_one_per_suite.json
# full fuzz→test pipeline: build the 45/55 split, fuzz, then evaluate the top templates
python baselines/agentvigil/train_test_split.py
python baselines/agentvigil/AgentDojo.py -c baselines/agentvigil/agentvigil_fuzzing_set.json
python baselines/agentvigil/update_testing_config.py --fuzzing-results <...> --testing-config baselines/agentvigil/agentvigil_testing_set.json
python baselines/agentvigil/AgentDojo.py -c baselines/agentvigil/agentvigil_testing_set.json
# InjecAgent
python baselines/agentvigil/InjecAgent.py -c baselines/agentvigil/agentvigil_injecagent.json
```

Defense configs: `agentvigil_defense_transformers_pi.json`. See its README for the MCTS
knobs (`iterations`, `exploration_weight`, `mutations_per_iteration`, …).

## AutoHijacker — [`autohijacker/`](autohijacker/APPENDIX_AUTOHIJACKER_REPRODUCTION.md)

Two-stage: train an attack memory on diverse (document, goal) pairs, then one-step-generate
at test time. `APPENDIX_AUTOHIJACKER_REPRODUCTION.md` documents the algorithm and mapping to
the paper.

```bash
python baselines/autohijacker/autohijacker_agentdojo_runner.py \
    --config baselines/autohijacker/autohijacker_agentdojo_config.json --output runs/autohijacker/agentdojo
python baselines/autohijacker/autohijacker_injecagent_runner.py \
    --config baselines/autohijacker/autohijacker_injecagent_config.json --output runs/autohijacker/injecagent
```

Defense variants: `autohijacker_agentdojo_{defense,pidetector,repeat}_config.json`.

## TopicAttack — [`topicattack/`](topicattack/)

Vendored upstream implementation (EMNLP 2025) plus the glue to run it against our benchmark
sessions under each defense. **Third-party code — read [`topicattack/NOTICE`](topicattack/NOTICE)
before redistributing.** The defense-sweep workflow is in
`topicattack/DEFENSE_EVALUATION_GUIDE.md`.

## Static / ChatInject — [`static/`](static/)

* **ChatInject** (`static/chatinject/` + `static/chatinject_runs/`) — multi-turn rapport
  dialogues that end in the malicious instruction. Run one AgentDojo suite:

  ```bash
  python -m baselines.static.chatinject_runs.run_chatinject \
      --suite banking --model gpt-4.1-2025-04-14 --output-dir runs/chatinject/logs/banking
  python -m baselines.static.chatinject_runs.aggregate_results          # Table II row (no defense)
  python -m baselines.static.chatinject_runs.aggregate_with_defenses    # Table III (all defenses)
  ```

  `--defense {transformers_pi_detector,repeat_user_prompt,spotlighting_with_delimiting}`
  selects a defense; outputs go to `runs/chatinject/logs/full_<defense>/<suite>/`.

* **Ignore-Previous / Important-Instructions** (`static/injecagent_static/`) — the classic
  fixed-template attacks on InjecAgent:

  ```bash
  bash baselines/static/injecagent_static/run.sh \
      --model-type GPT --model-name gpt-4.1-2025-04-14
  ```
