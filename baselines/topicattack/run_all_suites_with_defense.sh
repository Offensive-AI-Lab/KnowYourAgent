#!/bin/bash

################################################################################
# Run TopicAttack payloads against all AgentDojo suites with defense
# Includes all injection tasks for each suite
################################################################################

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${SCRIPT_DIR}/topicattack-main/data"
DEFENSE="spotlighting_with_delimiting"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="${SCRIPT_DIR}/logs/all_suites_${TIMESTAMP}"

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "=============================================================================="
echo "TopicAttack Defense Evaluation - All Suites"
echo "=============================================================================="
echo "Defense: $DEFENSE"
echo "Data directory: $DATA_DIR"
echo "Output directory: $OUTPUT_DIR"
echo "Timestamp: $TIMESTAMP"
echo "=============================================================================="

# Define suites and their payload patterns
# Each suite may have different task structures, so we handle them individually
declare -A SUITES
SUITES["banking"]="agentdojo_banking*_attack_complete.json"
SUITES["slack"]="agentdojo_slack*_attack_complete.json"
SUITES["workspace"]="agentdojo_workspace*_attack_complete.json"
SUITES["travel"]="agentdojo_travel*_attack_complete.json"

TOTAL_SUITES=${#SUITES[@]}
SUITE_COUNT=0

# Track results
RESULTS_FILE="${OUTPUT_DIR}/summary_results.txt"
touch "$RESULTS_FILE"

for SUITE in banking slack workspace travel; do
    PATTERN="${SUITES[$SUITE]}"
    SUITE_COUNT=$((SUITE_COUNT + 1))
    
    echo ""
    echo "================================================================================"
    echo "[$SUITE_COUNT/$TOTAL_SUITES] Running suite: $SUITE"
    echo "Pattern: $PATTERN"
    echo "================================================================================"
    
    # Count files matching pattern
    FILE_COUNT=$(ls -1 "${DATA_DIR}/${PATTERN}" 2>/dev/null | wc -l)
    
    if [ "$FILE_COUNT" -eq 0 ]; then
        echo "❌ No payload files found for suite: $SUITE"
        echo "$SUITE: NO FILES FOUND" >> "$RESULTS_FILE"
        continue
    fi
    
    echo "ℹ️  Found $FILE_COUNT payload file(s) for suite: $SUITE"
    
    # Create suite-specific log file
    SUITE_LOG="${OUTPUT_DIR}/${SUITE}_${DEFENSE}.log"
    
    # Run the evaluation (suite-specific defaults are now handled by the script)
    echo "Starting evaluation... (logging to $SUITE_LOG)"
    
    if python "${SCRIPT_DIR}/run_topicattack_with_defense.py" \
        --payload_patterns "${DATA_DIR}/${PATTERN}" \
        --suite_name "$SUITE" \
        --defense_name "$DEFENSE" \
        --log_file "$SUITE_LOG" \
        --verbose; then
        
        echo "✅ Suite '$SUITE' completed successfully"
        echo "$SUITE: SUCCESS" >> "$RESULTS_FILE"
        
        # Extract summary from log
        if grep -q "DEFENSE EVALUATION SUMMARY" "$SUITE_LOG"; then
            echo "   Summary:"
            grep "ASR\|Utility\|Total entries" "$SUITE_LOG" | tail -3 | sed 's/^/   /'
        fi
    else
        echo "❌ Suite '$SUITE' failed"
        echo "$SUITE: FAILED" >> "$RESULTS_FILE"
    fi
done

echo ""
echo "=============================================================================="
echo "FINAL SUMMARY"
echo "=============================================================================="
cat "$RESULTS_FILE"
echo ""
echo "All logs saved to: $OUTPUT_DIR"
echo "=============================================================================="

