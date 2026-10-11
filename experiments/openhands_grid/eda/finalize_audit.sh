#!/bin/bash
# Finalize the 3-pass audit. Runs the aggregator, the per-cell log re-scorer, and
# verify_runs.py on every new run dir, writing each script's FULL output to a file
# under cobra_runs/eda/audit/ so the numbers are independently checkable (no
# hand-typed results). Meant to run after the pass3 patch job finishes
# (SLURM dependency afterany:<patch_job>).
set -uo pipefail
cd "$(dirname "$0")/../.."   # repo root

OUT=cobra_runs/eda/audit
mkdir -p "$OUT"
STAMP=$(date '+%Y-%m-%d %H:%M:%S')

PASS2=cobra_runs/results/cobra_openhands_20260524_170814
PASS3=cobra_runs/results/cobra_openhands_20260524_230606
PATCH=$(grep -l '"label": "pass3_patch' cobra_runs/results/cobra_openhands_*/run_meta.json 2>/dev/null | xargs -n1 dirname)

{
  echo "# 3-pass audit generated $STAMP"
  echo "# pass2 dir: $PASS2"
  echo "# pass3 dir: $PASS3"
  echo "# pass3 patch dir(s): $PATCH"
  echo "#"
  echo "# files in this dir:"
  echo "#   aggregate_passes.txt  - per-cell x per-pass matrix + per-pass/injection/repo ASR"
  echo "#   rescore_logs.txt      - per-SUCCESS triggering command + FAILURE near-miss scan"
  echo "#   verify_*.txt          - log-vs-revalidation determinism per run dir"
  echo "#   ../passes/per_cell_per_pass.csv - machine-readable 210-row table"
} > "$OUT/README.txt"

echo "[finalize] aggregate_passes.py"
uv run --no-sync python cobra_runs/eda/aggregate_passes.py > "$OUT/aggregate_passes.txt" 2>&1
echo "[finalize] rescore_logs.py"
uv run --no-sync python cobra_runs/eda/rescore_logs.py     > "$OUT/rescore_logs.txt" 2>&1
echo "[finalize] verify_runs.py pass2"
uv run --no-sync python cobra_runs/verify_runs.py "$PASS2" > "$OUT/verify_pass2.txt" 2>&1
echo "[finalize] verify_runs.py pass3"
uv run --no-sync python cobra_runs/verify_runs.py "$PASS3" > "$OUT/verify_pass3.txt" 2>&1
for p in $PATCH; do
  name=$(basename "$p")
  echo "[finalize] verify_runs.py $name"
  uv run --no-sync python cobra_runs/verify_runs.py "$p" > "$OUT/verify_${name}.txt" 2>&1
done
echo "[finalize] check_consistency.py"
uv run --no-sync python cobra_runs/eda/check_consistency.py > "$OUT/check_consistency.txt" 2>&1
echo "[finalize] consistency exit = $?"

{
  echo "AUDIT COMPLETE $(date '+%Y-%m-%d %H:%M:%S')"
  echo
  ls -la "$OUT"
} > "$OUT/STATUS.txt"
echo "[finalize] done -> $OUT/STATUS.txt"
