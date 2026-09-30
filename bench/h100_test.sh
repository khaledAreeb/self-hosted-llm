#!/bin/bash
# Measure the H100 deployment: the phase 3 load test on the GPU deploy.py now uses.
#
# STATUS 2026-09-30: NOT USABLE YET. deploy.py is back on the A100 after the H100
# crash-looped at startup (DeepGEMM needs CUDA 12.9; the image is 12.8.1). Before
# running this: apply the fix described above GPU in deploy.py, set
# GPU = "H100!", and expect the first start to be the real test.
#
#   bench/h100_test.sh
#
# deploy.py switched to GPU = "H100!" on 2026-09-29. This script checks that
# the switch was worth it, against the A100 results kept in
# bench/results/2026-09-29/. What it does, in order:
#   1. asks for your Modal balance and stops unless it is at least $3
#   2. deploys deploy.py (the H100 configuration)
#   3. waits for the cold start, watching the logs for fatal errors
#   4. confirms from vLLM's own startup log which GPU really ran
#   5. runs: validate 1, interactive 4 / 8 / 16 / 30, agent 8, and the
#      long-document interference test, all labelled *-h100
#   6. ALWAYS (even on error or Ctrl-C): stops the app and deploys again, which
#      releases the GPU at once and leaves the endpoint up (no container
#      until the next request)
#   7. prints the H100 rows next to the A100 rows from 2026-09-29
#
# Expected: ~27 GPU-minutes at ~$4.39/hr (H100 + CPU/memory), about $2.00-2.50.
# Anyone else using the endpoint during the run will hit the test GPU.
set -uo pipefail

cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
URL="https://dev-khaled-areeb--qwen38-27b-serve.modal.run"
M="./venv/bin/modal"
FATAL="vllm serve: error|Engine core initialization failed|OutOfMemoryError|RuntimeError:|ValueError:|NotImplementedError"
DAY=$(date +%F)
OUT="bench/results/$DAY"
TMP=$(mktemp -d)
mkdir -p "$OUT"

# --- 1. money gate ----------------------------------------------------------
echo "This run costs about \$2.00-2.50 of GPU time (H100, ~27 minutes)."
read -r -p "Current Modal balance from the dashboard, in dollars (e.g. 4.75): " BAL
if ! python3 -c "import sys; sys.exit(0 if float('$BAL') >= 3.0 else 1)" 2>/dev/null; then
  echo "Balance under \$3 (or not a number): not running. Nothing was deployed."; exit 1
fi
read -r -p "Run the H100 test now? [y/N] " OK
[ "$OK" = "y" ] || { echo "Cancelled. Nothing was deployed."; exit 1; }

# --- 6. always restore the real deployment ----------------------------------
restore() {
  echo; echo "=== releasing the GPU: stop + deploy === $(date +%T)"
  timeout 90 $M app stop qwen38-27b --yes >/dev/null 2>&1; sleep 4
  timeout 300 $M deploy deploy.py 2>&1 | grep -E "deployed in|rror" | head -2
  sleep 5
  echo "containers running (expect 0): $($M container list --json 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
  rm -rf "$TMP" bench/__pycache__ eval/__pycache__
}
trap restore EXIT

# --- 2. deploy deploy.py (H100) ---------------------------------------------
grep -q '^GPU = "H100' deploy.py || { echo "deploy.py is not set to an H100 GPU; nothing to measure."; exit 2; }
echo "=== deploying $(grep '^GPU = ' deploy.py) === $(date +%T)"
timeout 90 $M app stop qwen38-27b --yes >/dev/null 2>&1; sleep 4   # a running A100 container would not switch otherwise
timeout 300 $M deploy deploy.py 2>&1 | tee "$TMP/deploy.log" | grep -E "deployed in"
grep -q "deployed in" "$TMP/deploy.log" || { echo 'Deploy failed. If Modal rejected "H100!", set GPU = "H100" in deploy.py and rerun.'; cat "$TMP/deploy.log" | tail -5; exit 2; }

# --- 3. cold start, with early failure detection ----------------------------
S=$(date +%s); LAST=0
while true; do
  C=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 30 "$URL/v1/models" -H "Authorization: Bearer $MODAL_PROXY_TOKEN" 2>/dev/null)
  [ "$C" = "200" ] && break
  E=$(( $(date +%s) - S ))
  if [ $(( E - LAST )) -ge 90 ]; then LAST=$E
    timeout 45 $M app logs qwen38-27b > "$TMP/probe.log" 2>&1
    grep -qE "$FATAL" "$TMP/probe.log" && { echo "EARLY FAILURE at ${E}s:"; grep -E "$FATAL" "$TMP/probe.log" | tail -3 | cut -c1-240; exit 2; }
  fi
  sleep 10; [ $E -gt 1500 ] && { echo "TIMEOUT waiting for the H100 container"; exit 1; }
done
echo "cold_start=$(( $(date +%s) - S ))s  ready $(date +%T)"

# --- 4. which GPU really ran? -----------------------------------------------
timeout 60 $M app logs qwen38-27b > "$OUT/startup-h100.log" 2>&1
echo "GPU reported by the container:"
grep -ohiE "NVIDIA (H100|H200|A100)[^,'\"]*" "$OUT/startup-h100.log" | sort -u | head -3
grep -oE "kv cache group sizes \[[0-9, ]+\]" "$OUT/startup-h100.log" | head -1

# --- 5. the measurements ----------------------------------------------------
bench/run.sh validate 1 --label validate-1-h100
for N in 4 8 16 30; do bench/run.sh interactive $N --label interactive-$N-h100; done
bench/run.sh agent 8 --label agent-8-h100
bench/run.sh interactive 8 --label interference-8-h100 --requests 70 &
LOAD=$!
sleep 40
python3 bench/interference.py interference-8-h100
wait $LOAD

# --- 7. compare --------------------------------------------------------------
echo; echo "=== H100 results ($OUT) ==="
python3 bench/summarize.py "$OUT" | grep -E "^## |^\| level|h100"
echo; echo "=== A100 reference (bench/results/2026-09-29) ==="
python3 bench/summarize.py bench/results/2026-09-29 | grep -E "^\| level|^\| (validate-1|interactive-(4|8|16|30)|agent-8|interference-8) "
echo; echo "Done $(date +%T). Read your new balance from the dashboard."
