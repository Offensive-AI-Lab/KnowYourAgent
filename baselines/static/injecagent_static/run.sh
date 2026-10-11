#!/bin/bash
# Run the Ignore-Previous / Important-Instructions static baseline on InjecAgent.
# Usage:
#   bash baselines/static/injecagent_static/run.sh                                   # defaults (GPT, dh+ds)
#   bash baselines/static/injecagent_static/run.sh --model-type OpenRouter --model-name meta-llama/llama-3.3-70b-instruct
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"
python baselines/static/injecagent_static/run_important_instructions.py "$@"
