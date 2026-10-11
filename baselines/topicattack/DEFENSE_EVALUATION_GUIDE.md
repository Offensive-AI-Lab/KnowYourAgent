# TopicAttack Defense Evaluation Guide

## Payload File Structure

TopicAttack payload files are organized by suite and injection task:
- **File naming**: `agentdojo_{suite}{injection_task_number}_attack_complete.json`
- **Example**: `agentdojo_slack1_attack_complete.json` contains 21 payloads for `injection_task_1`
- **Entry structure**: Each entry in the file corresponds to a different `user_task` (entry 0 = `user_task_0`, entry 1 = `user_task_1`, etc.)

### Example Slack Suite Structure
- `agentdojo_slack1_attack_complete.json` → 21 entries for injection_task_1 (user_task_0 through user_task_20)
- `agentdojo_slack2_attack_complete.json` → 21 entries for injection_task_2 (user_task_0 through user_task_20)
- `agentdojo_slack3_attack_complete.json` → 21 entries for injection_task_3
- etc. (up to injection_task_5 for slack)

## How the Script Works

The script **automatically detects** the injection task number from the filename and the user task number from the entry index. You don't need to specify task pairs explicitly.

For each payload file:
1. Extracts `injection_task_X` from filename (e.g., `slack1` → `injection_task_1`)
2. For each entry in the file (index 0, 1, 2...):
   - Uses `user_task_{index}` (entry 0 → `user_task_0`, entry 1 → `user_task_1`, etc.)
   - Uses the injection task from step 1
   - Runs evaluation with the correct task pair

## Prerequisites

1. Start the AgentDojo REST API server first:
```bash
cd .
python benchmarks/agentdojo/src/rest_api.py --port 5000
```

2. Ensure you have the attack payload files in the `data/` directory. Available payloads include:
   - `data/agentdojo_banking0_attack_complete.json` through `agentdojo_banking8_attack_complete.json`
   - `data/agentdojo_slack1_attack_complete.json` through `agentdojo_slack5_attack_complete.json`
   - `data/agentdojo_workspace0_attack_complete.json` through `agentdojo_workspace5_attack_complete.json`
   - `data/agentdojo_travel_attack_complete.json` through `agentdojo_travel6_attack_complete.json`

## Quick Start

### 1. Run a Single Payload File (Auto-detects tasks)

```bash
cd baselines/topicattack

# This automatically detects injection_task_1 from the filename
# and uses user_task_0 through user_task_20 for each entry
python run_topicattack_with_defense.py \
    --payload_file topicattack-main/data/agentdojo_slack1_attack_complete.json \
    --suite_name slack \
    --defense_name spotlighting_with_delimiting \
    --verbose
```

### 2. Run All Injection Tasks for a Suite

```bash
# Automatically discovers all slack*.json files
# Each file handles its specific injection_task automatically
python run_topicattack_with_defense.py \
    --payload_patterns "topicattack-main/data/agentdojo_slack*_attack_complete.json" \
    --suite_name slack \
    --defense_name spotlighting_with_delimiting \
    --verbose
```

This will process:
- `agentdojo_slack1_attack_complete.json` with injection_task_1
- `agentdojo_slack2_attack_complete.json` with injection_task_2
- `agentdojo_slack3_attack_complete.json` with injection_task_3
- etc.

### 3. Run All Suites (Banking, Slack, Workspace, Travel)

```bash
./run_all_suites_with_defense.sh
```

This script runs all suites and all their injection tasks, automatically detecting the correct task pairings.

## Advanced Options

### Override Auto-Detection (Manual Task Pairs)

If needed, you can explicitly specify task pairs:

```bash
python run_topicattack_with_defense.py \
    --payload_file topicattack-main/data/agentdojo_slack1_attack_complete.json \
    --suite_name slack \
    --defense_name spotlighting_with_delimiting \
    --tasks user_task_1:injection_task_1 \
    --verbose
```

**Note**: When you provide explicit `--tasks`, auto-detection is disabled and the same task pair is used for all entries.

### Different Defense

```bash
python run_topicattack_with_defense.py \
    --payload_patterns "topicattack-main/data/agentdojo_banking*_attack_complete.json" \
    --suite_name banking \
    --defense_name repeat_user_prompt \
    --verbose
```

### Different Model

```bash
python run_topicattack_with_defense.py \
    --payload_patterns "topicattack-main/data/agentdojo_banking*_attack_complete.json" \
    --suite_name banking \
    --defense_name spotlighting_with_delimiting \
    --model_name gpt-4-1106-preview \
    --verbose
```

### Custom Log File

```bash
python run_topicattack_with_defense.py \
    --payload_patterns "topicattack-main/data/agentdojo_slack*_attack_complete.json" \
    --suite_name slack \
    --defense_name spotlighting_with_delimiting \
    --log_file my_results.log \
    --verbose
```

## Understanding the Output

### Metrics

- **ASR (Attack Success Rate)**: Percentage of attacks that successfully bypassed the defense
- **Utility**: Percentage of user tasks that were completed correctly
- **Total entries**: Number of payloads tested
- **Errors**: Number of runs that failed due to API errors

### Log File Example

```
[08:43:00] Payload file 1/6: topicattack-main/data/agentdojo_slack1_attack_complete.json
[08:43:00] Auto-detected injection_task_1 from filename
[08:43:00] 
----------------------------------------------------------------------
[08:43:00] Entry 1/21
[08:43:00]   instruction : Read the content on webpage...
[08:43:00]   task pair   : user_task_0:injection_task_1
[08:43:01]   session_id  : b9123b7a09914b68864a551f6613f212
[08:43:07]   security (attack succeeded): False
[08:43:07]   utility  (task completed) : True
```

Notice:
- **Auto-detected**: Shows which injection_task was extracted from the filename
- **task pair**: Shows the exact user_task:injection_task combination being tested
- **Entry index**: Determines the user_task number

### Final Summary

```
======================================================================
DEFENSE EVALUATION SUMMARY: spotlighting_with_delimiting
======================================================================
  Total entries       : 126
  Successful runs     : 126/126
  Errors              : 0
  ASR  (attack)       : 28.57%  (36/126)
  Utility (task)      : 98.41%  (124/126)
======================================================================
```

## File Organization

After running, logs are organized as:
```
logs/
├── defense_spotlighting_with_delimiting_2026-05-03_084300.txt
├── defense_repeat_user_prompt_2026-05-03_090000.txt
└── all_suites_20260503_084300/
    ├── banking_spotlighting_with_delimiting.log
    ├── slack_spotlighting_with_delimiting.log
    ├── workspace_spotlighting_with_delimiting.log
    └── travel_spotlighting_with_delimiting.log
```

## Troubleshooting

### "Could not extract injection task from filename"
- Make sure you're using files matching the pattern `agentdojo_{suite}{number}_attack_complete.json`
- Example: `agentdojo_slack1_attack_complete.json` ✓
- Invalid: `agentdojo_slack_attack_complete.json` ✗ (missing number)

### Same user prompt appearing in logs
- This can happen if multiple injection tasks access the same web resource or if the user task is consistent
- Check the `task pair` line to verify different task combinations are being used
- Each entry should show a different user_task number (Entry 1 should be user_task_0, Entry 2 should be user_task_1, etc.)

### Cannot reach REST API at http://127.0.0.1:5000
- Ensure the REST API server is running: `python benchmarks/agentdojo/src/rest_api.py --port 5000`
- Check that port 5000 is not blocked by firewall

## Performance Tips

1. **Run full suites**: Use glob patterns to test all injection tasks at once
2. **Verbose mode**: Only use `--verbose` when investigating specific issues (increases I/O)
3. **Parallel runs**: Run different suites in separate terminals to test multiple defenses simultaneously
4. **Custom output dirs**: Use `--log_file` to organize results by date or experiment

