# TopicAttack

Indirect prompt injection via gradual **topic transition**. This directory vendors the
upstream reference implementation (`topicattack-main/`, EMNLP 2025) and adds the glue to run
it against this repo's benchmark sessions under each defense.

**Third-party code — read [`NOTICE`](NOTICE) before redistributing this directory.**

* `run_topicattack_with_defense.py` — run TopicAttack against a benchmark under a chosen defense.
* `run_defense_comparison.py`, `run_all_suites_with_defense.sh` — the full defense sweep.
* [`DEFENSE_EVALUATION_GUIDE.md`](DEFENSE_EVALUATION_GUIDE.md) — step-by-step evaluation workflow.
* [`FIX_SUMMARY.md`](FIX_SUMMARY.md) — notes on the adaptation to this repo's APIs.

Set `OPENAI_API_KEY` in your environment (the vendored `chatbot.py` reads it from there).
