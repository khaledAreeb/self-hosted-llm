"""
Record vLLM's own counters while a load test runs.

    set -a; . ./.env; set +a
    python3 bench/metrics_sampler.py bench/results/<date>/interactive-8.metrics.csv

Polls the server's Prometheus endpoint (/metrics, same URL and token as the API)
every 5 seconds and appends one CSV row per poll until stopped with Ctrl-C or
SIGTERM (run.sh stops it at the end of each level).

    running        requests the GPU is working on right now
    waiting        requests queued inside vLLM, not started yet
    kv_usage       fraction of the KV cache in use (0-1)
    preemptions    total requests evicted to free KV cache (a counter)
    prefix_hits    prefix-cache tokens served from cache (a counter)
    prefix_queries prefix-cache tokens looked up (a counter)
    gen_tokens     total tokens generated (a counter)

Reading them: waiting > 0 means requests are queueing; kv_usage near 1 with
preemptions rising means memory is the limit; neither means the GPU is simply
compute-bound.

Only start this against a WARM container. A /metrics request is a request like
any other: polling a cold endpoint would start a GPU container on its own.

Metric names differ between vLLM versions (the KV metric was renamed from
gpu_cache_usage_perc to kv_cache_usage_perc), so they are matched by pattern,
not hard-coded. A metric the server does not export is left blank; a failed
poll is logged and sampling continues.
"""

import csv
import os
import re
import signal
import sys
import time
import urllib.request

URL = os.environ.get("METRICS_URL", "https://dev-khaled-areeb--qwen38-27b-serve.modal.run/metrics")
INTERVAL_S = 5

# column -> regex matched against the metric name (label sets are summed)
SERIES = {
    "running": r"^vllm:num_requests_running$",
    "waiting": r"^vllm:num_requests_waiting$",
    "kv_usage": r"^vllm:(kv|gpu)_cache_usage_perc$",
    "preemptions": r"^vllm:num_preemptions(_total)?$",
    "prefix_hits": r"^vllm:(gpu_)?prefix_cache_hits(_total)?$",
    "prefix_queries": r"^vllm:(gpu_)?prefix_cache_queries(_total)?$",
    "gen_tokens": r"^vllm:generation_tokens(_total)?$",
}
LINE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(\S+)")


def parse(text):
    """Prometheus text -> {column: summed value or None}, plus the names matched."""
    values = {col: None for col in SERIES}
    matched = {col: set() for col in SERIES}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        m = LINE.match(line)
        if not m:
            continue
        name, value = m.group(1), m.group(3)
        try:
            v = float(value)
        except ValueError:
            continue
        for col, pattern in SERIES.items():
            if re.match(pattern, name):
                values[col] = (values[col] or 0.0) + v
                matched[col].add(name)
    return values, matched


def fetch(token):
    req = urllib.request.Request(URL, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode()


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: metrics_sampler.py <output.csv>")
    token = os.environ["MODAL_PROXY_TOKEN"]
    out = sys.argv[1]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    stop = False

    def handle(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)

    reported = False
    with open(out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", *SERIES])
        while not stop:
            started = time.time()
            try:
                values, matched = parse(fetch(token))
                writer.writerow([round(started, 1), *(values[c] for c in SERIES)])
                f.flush()
                if not reported:
                    # Record which names this vLLM version actually uses.
                    for col in SERIES:
                        names = ", ".join(sorted(matched[col])) or "NOT EXPORTED"
                        print(f"sampler: {col:14} <- {names}", file=sys.stderr)
                    reported = True
            except Exception as e:  # keep sampling through a bad poll
                print(f"sampler: poll failed at {started:.0f}: {e}", file=sys.stderr)
            time.sleep(max(0.0, INTERVAL_S - (time.time() - started)))


if __name__ == "__main__":
    main()
