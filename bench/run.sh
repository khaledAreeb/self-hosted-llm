#!/bin/bash
# Run one load-test level: one workload at one concurrency.
#
#   bench/run.sh interactive 8            # 8 requests always in flight
#   bench/run.sh agent 4
#   bench/run.sh interactive 8 --label interactive-8-repeat
#   bench/run.sh interactive 4 --target http://127.0.0.1:8123 --no-sampler   # mock server
#   bench/run.sh interactive 8 --label interference-8 --requests 60   # see interference.py
#
# Writes bench/results/<date>/<label>.json  (GuideLLM's full results)
#        bench/results/<date>/<label>.metrics.csv  (vLLM's own counters, 5 s)
#        bench/results/<date>/<label>.log
#
# The endpoint must already be WARM: both GuideLLM's first request and the
# metrics sampler would otherwise trigger (and time) a cold start.
#
# How much each level runs (design.md): keep N requests in flight until
# max(20, 3N) requests remain after summarize.py drops the first and last 10%,
# or 4 minutes pass. A level stopped by the 4-minute cap before 20
# measured requests is flagged by summarize.py, not quietly reported.
set -euo pipefail

WORKLOAD=${1:?usage: run.sh <interactive|agent|validate> <concurrency> [--label L] [--target URL] [--no-sampler]}
STREAMS=${2:?usage: run.sh <interactive|agent|validate> <concurrency> ...}
shift 2
LABEL="$WORKLOAD-$STREAMS"
TARGET="https://dev-khaled-areeb--qwen38-27b-serve.modal.run"
SAMPLER=1
while [ $# -gt 0 ]; do
  case "$1" in
    --label) LABEL=$2; shift 2 ;;
    --target) TARGET=$2; shift 2 ;;
    --no-sampler) SAMPLER=0; shift ;;
    --requests) FORCE_TOTAL=$2; shift 2 ;;   # override, e.g. to span a long request
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."
BENCH=bench
OUT="$BENCH/results/$(date +%F)"
mkdir -p "$OUT"

# The proxy token comes from .env at run time and is never written to disk.
# A run against the mock server uses a dummy key, so a leak check can look for it.
if [ -z "${MODAL_PROXY_TOKEN:-}" ]; then set -a; . ./.env; set +a; fi
KEY=${BENCH_API_KEY:-$MODAL_PROXY_TOKEN}

# Enough requests that max(20, 3N) remain after dropping 10% warmup + 10% cooldown.
MEASURED=$(( STREAMS * 3 > 20 ? STREAMS * 3 : 20 ))
TOTAL=$(( (MEASURED * 10 + 7) / 8 ))
TOTAL=${FORCE_TOTAL:-$TOTAL}

case "$WORKLOAD" in
  interactive)
    # 12 real coding and report prompts; the model stops naturally, capped at 4,000.
    # split=train: GuideLLM's JSON loader otherwise returns a dict of splits and fails.
    DATA='{"kind": "json_file", "path": "'"$BENCH"'/datasets/interactive.json", "load_kwargs": {"split": "train"}}'
    MAX_TOKENS=4000 ;;
  validate)
    # eval/decode_bench.py's prompt and cap, so the two tools measure identical
    # work and can be compared (task 3.4). Run it at concurrency 1.
    DATA='{"kind": "json_file", "path": "'"$BENCH"'/datasets/validate.json", "load_kwargs": {"split": "train"}}'
    MAX_TOKENS=1200 ;;
  agent)
    # Coding-agent shape: one 16K-token context shared by every request, 1K
    # unique tokens each, a short 300-token step. The shared prefix is the point:
    # real agents resend their context, and the prefix cache is what serves it.
    # (GuideLLM 0.7.4 takes the shared prefix as prefix_buckets, not flat fields.)
    DATA='{"kind": "synthetic_text", "prompt_tokens": 1000, "output_tokens": 300, "prefix_buckets": [{"bucket_weight": 100, "prefix_count": 1, "prefix_tokens": 16000}]}'
    MAX_TOKENS=300 ;;
  *) echo "unknown workload $WORKLOAD" >&2; exit 2 ;;
esac

# Backend as JSON so the key never has to survive shell quoting. Temperature 0
# makes two configurations (e.g. MTP on vs off) generate the same tokens, so
# their comparison is like for like.
BACKEND=$(KEY="$KEY" TARGET="$TARGET" MAX_TOKENS="$MAX_TOKENS" python3 -c '
import json, os
print(json.dumps({"kind": "openai_http", "target": os.environ["TARGET"],
                  "request_format": "/v1/chat/completions",
                  "api_key": os.environ["KEY"],
                  "max_tokens": int(os.environ["MAX_TOKENS"]),
                  "extras": {"body": {"temperature": 0}}}))')

# No GuideLLM warmup/cooldown: in 0.7.4 its time-based default discards the
# first 24 s of a 240 s cap, and its request-based mode excluded nothing.
# summarize.py drops the first and last 10% of requests itself, visibly.
PROFILE='{"kind": "concurrent", "streams": ['"$STREAMS"']}'

if [ "$SAMPLER" = 1 ]; then
  python3 "$BENCH/metrics_sampler.py" "$OUT/$LABEL.metrics.csv" 2>>"$OUT/$LABEL.log" &
  SAMPLER_PID=$!
  trap 'kill $SAMPLER_PID 2>/dev/null || true' EXIT
fi

echo "$(date +%T) $LABEL: $STREAMS in flight, $TOTAL requests ($MEASURED measured), cap 240 s" | tee -a "$OUT/$LABEL.log"
"$BENCH/.venv/bin/guidellm" run \
  --backend "$BACKEND" \
  --tokenizer kind=huggingface_auto,model=Qwen/Qwen3.8-27B-FP8 \
  --profile "$PROFILE" \
  --constraint "kind=max_requests,count=$TOTAL" \
  --constraint kind=max_duration,seconds=240 \
  --constraint kind=max_errors,count=10 \
  --data "$DATA" \
  --output "kind=json,path=$OUT/$LABEL.json" \
  --label "workload=$WORKLOAD" --label "streams=$STREAMS" \
  --disable-console-interactive \
  >>"$OUT/$LABEL.log" 2>&1
echo "$(date +%T) $LABEL: done -> $OUT/$LABEL.json" | tee -a "$OUT/$LABEL.log"
