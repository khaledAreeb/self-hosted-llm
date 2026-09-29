"""Checks bench/metrics_sampler.py without a GPU: parsing, and surviving a failed poll.

    python3 bench/tests/test_sampler.py
"""

import csv
import http.server
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import metrics_sampler  # noqa: E402

SAMPLE = open(os.path.join(HERE, "prometheus_sample.txt")).read()

# 1. Parsing: decoys (_created timestamps, histogram buckets) must not match.
values, matched = metrics_sampler.parse(SAMPLE)
want = {"running": 7.0, "waiting": 2.0, "kv_usage": 0.4375, "preemptions": 3.0,
        "prefix_hits": 96000.0, "prefix_queries": 120000.0, "gen_tokens": 51234.0}
assert values == want, values

# A server that does not export a metric leaves it blank rather than failing.
values, _ = metrics_sampler.parse("vllm:num_requests_running 1\n")
assert values["running"] == 1.0 and values["kv_usage"] is None, values

# 2. A failed poll is logged and sampling continues.
calls = {"n": 0}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        calls["n"] += 1
        if calls["n"] == 2:                      # second poll fails
            self.send_response(500); self.end_headers(); return
        body = SAMPLE.encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)

    def log_message(self, *_):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
out = os.path.join(tempfile.mkdtemp(), "m.csv")
env = {**os.environ, "METRICS_URL": f"http://127.0.0.1:{server.server_port}/metrics",
       "MODAL_PROXY_TOKEN": "dummy-token"}
proc = subprocess.Popen([sys.executable, os.path.join(HERE, "..", "metrics_sampler.py"), out],
                        env=env, stderr=subprocess.PIPE, text=True)
time.sleep(13)                                   # ~3 polls at 5 s
proc.send_signal(signal.SIGTERM)
_, err = proc.communicate(timeout=10)
rows = list(csv.DictReader(open(out)))
assert calls["n"] >= 3, calls
assert len(rows) == calls["n"] - 1, (len(rows), calls)   # every poll but the failed one
assert "poll failed" in err, err
assert rows[0]["running"] == "7.0" and rows[-1]["kv_usage"] == "0.4375", rows
print(f"PASS: parse exact; {calls['n']} polls, 1 failed and logged, {len(rows)} rows written")
