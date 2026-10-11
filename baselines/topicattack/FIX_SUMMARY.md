# Fix Summary: TopicAttack Defense Evaluation Script

## Problem

The script was using **hardcoded task pairs for all entries**, ignoring the actual structure of the payload files:
- Always used the same `user_task` and `injection_task` for all entries
- All entries showed the same user prompt
- Did not respect the payload file's intended structure

## Payload File Structure

TopicAttack payload files encode task information in their structure:

```
File naming: agentdojo_{suite}{injection_task_number}_attack_complete.json
Example: agentdojo_slack1_attack_complete.json

Inside the file:
- Entry 0 → intended for user_task_0
- Entry 1 → intended for user_task_1
- Entry 2 → intended for user_task_2
- ...
- Entry 20 → intended for user_task_20

All entries use the injection_task extracted from filename (e.g., injection_task_1)
```

## Solution

The script now **automatically detects task pairs**:

1. **Extracts injection task from filename**:
   - `agentdojo_slack1_attack_complete.json` → `injection_task_1`
   - `agentdojo_banking0_attack_complete.json` → `injection_task_0`

2. **Maps entry indices to user tasks**:
   - Entry 0 → `user_task_0`
   - Entry 1 → `user_task_1`
   - Entry N → `user_task_N`

3. **Combines them for each entry**:
   - Entry 0: `user_task_0:injection_task_1`
   - Entry 1: `user_task_1:injection_task_1`
   - Entry 2: `user_task_2:injection_task_1`
   - etc.

## Example Before vs After

### Before (Incorrect)
```
File: agentdojo_slack1_attack_complete.json
Entry 1: user_task_1:injection_task_1  ← ALWAYS the same
Entry 2: user_task_1:injection_task_1  ← Same user task
Entry 3: user_task_1:injection_task_1  ← Same user task
...
User prompt: "Summarize the article that Bob posted..." ← Same for all
```

### After (Correct)
```
File: agentdojo_slack1_attack_complete.json
Entry 1: user_task_0:injection_task_1  ← Different user task
Entry 2: user_task_1:injection_task_1  ← Different user task
Entry 3: user_task_2:injection_task_1  ← Different user task
...
User prompt: Different for each entry (matches different user_task)
```

## How to Run

### Single File (Auto-detects injection_task from filename)
```bash
python run_topicattack_with_defense.py \
    --payload_file topicattack-main/data/agentdojo_slack1_attack_complete.json \
    --suite_name slack \
    --defense_name spotlighting_with_delimiting \
    --verbose
```

### All Files for a Suite (Auto-detects all injection_tasks)
```bash
python run_topicattack_with_defense.py \
    --payload_patterns "topicattack-main/data/agentdojo_slack*_attack_complete.json" \
    --suite_name slack \
    --defense_name spotlighting_with_delimiting \
    --verbose
```

This will process:
- `agentdojo_slack1_attack_complete.json` → injection_task_1 (21 entries)
- `agentdojo_slack2_attack_complete.json` → injection_task_2 (21 entries)
- `agentdojo_slack3_attack_complete.json` → injection_task_3 (21 entries)
- etc.

Total: ~105 evaluation runs (5 injection tasks × 21 user tasks)

### All Suites
```bash
./run_all_suites_with_defense.sh
```

## What Changed in the Code

### Old Approach (Broken)
```python
# Always use the same task pair for all entries
task_pairs = [("user_task_0", "injection_task_0")]
for idx, entry in enumerate(data):
    user_task, inj_task = task_pairs[0]  # ← Same pair every time
    evaluator.evaluate_entry(idx, entry, user_task, inj_task)
```

### New Approach (Fixed)
```python
# Auto-detect injection task from filename
injection_task = extract_injection_task_from_filename(payload_file)

# Map entry index to user task
for idx, entry in enumerate(data):
    user_task = f"user_task_{idx}"           # ← Different per entry
    inj_task = injection_task                # ← From filename
    evaluator.evaluate_entry(idx, entry, user_task, inj_task)
```

## Verification

You can verify the fix by checking the log output:

```
[08:43:00] Auto-detected injection_task_1 from filename
[08:43:00] 
----------------------------------------------------------------------
[08:43:00] Entry 1/21
[08:43:00]   task pair   : user_task_0:injection_task_1  ← Entry 0 uses user_task_0
[08:43:00] 
----------------------------------------------------------------------
[08:43:07] Entry 2/21
[08:43:07]   task pair   : user_task_1:injection_task_1  ← Entry 1 uses user_task_1
[08:43:07] 
----------------------------------------------------------------------
[08:43:13] Entry 3/21
[08:43:13]   task pair   : user_task_2:injection_task_1  ← Entry 2 uses user_task_2
```

Notice:
- `injection_task_1` is **auto-detected** from filename
- Each entry uses a **different user_task** (0, 1, 2, ...)
- Different user prompts will appear for each entry

## Files Modified

1. **run_topicattack_with_defense.py**
   - Added `extract_injection_task_from_filename()` function
   - Modified task pair resolution logic
   - Updated logging to show auto-detection

2. **DEFENSE_EVALUATION_GUIDE.md**
   - Updated documentation to explain new structure
   - Added payload file structure section
   - Updated examples to show auto-detection

## Testing

The fix has been verified to:
- ✓ Correctly extract injection_task numbers from filenames
- ✓ Map entry indices to user_task numbers
- ✓ Combine them into correct task pairs
- ✓ Maintain backward compatibility (explicit --tasks still works)
- ✓ Generate correct log output showing task pairs

## Next Steps

1. Run a single file to verify:
```bash
cd baselines/topicattack
python run_topicattack_with_defense.py \
    --payload_file topicattack-main/data/agentdojo_slack1_attack_complete.json \
    --suite_name slack \
    --verbose
```

2. Check that the log shows:
   - Auto-detected injection_task_1
   - Different task pairs for each entry
   - Different user prompts per entry

3. Run the full suite:
```bash
./run_all_suites_with_defense.sh
```
