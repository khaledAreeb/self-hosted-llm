"""
Turn load-test results into one table per workload, and judge each level.

    python3 bench/summarize.py                         # newest results folder
    python3 bench/summarize.py bench/results/2026-09-29

Reads every <label>.json GuideLLM wrote (plus <label>.metrics.csv from the
sampler, when present) and prints, per concurrency level:

    ttft      time to first token (thinking included)
    visible   time to first VISIBLE token -- what a user actually waits for
    gen       per-request generation speed, tok/s
    total     whole request time
    tput      output tokens/s across all requests at this level
    fail      errored + incomplete (+ empty answers, for interactive)
    run/wait/kv/preempt   the server's own counters during the measured window

All percentiles are computed HERE from GuideLLM's per-request records rather
than taken from its summary, for two reasons found while building this:
  - GuideLLM's request-based warmup did not exclude anything in 0.7.4, so the
    first and last 10% of requests (by start time) are dropped here instead;
  - its per-request "output_tokens_per_second" includes the wait for the first
    token. Generation speed here is (tokens - 1) / (last token - first token),
    the same formula as eval/decode_bench.py, so the two can be compared.

A level is USABLE when it meets the targets fixed in design.md before any
results existed, and is flagged SHORT when fewer than 20 requests were measured.
"""

import csv
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TRIM = 0.10          # drop this share of requests at each end
MIN_SAMPLES = 20

# Fixed in design.md before any load result existed. Change them there first.
TARGETS = {
    "interactive": {"visible_p95_s": 20.0, "gen_p95_tok_s": 15.0, "fail_rate": 0.01},
    "agent": {"total_p95_s": 20.0, "fail_rate": 0.01},
}


def pct(values, p):
    """Percentile by linear interpolation; None for no data."""
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def level_stats(path):
    data = json.load(open(path))
    bench = data["benchmarks"][0]
    labels = ((data.get("config") or {}).get("metadata") or {}).get("labels") or {}
    streams = bench["config"]["strategy"].get("streams")
    workload = labels.get("workload") or os.path.basename(path).split("-")[0]

    reqs = []
    for status in ("successful", "errored", "incomplete"):
        for r in bench["requests"].get(status) or []:
            reqs.append((status, r))
    reqs.sort(key=lambda sr: sr[1]["request_start_time"] or 0)
    cut = int(len(reqs) * TRIM)
    measured = reqs[cut:len(reqs) - cut] if cut else reqs

    ttft, visible, gen, total, failed = [], [], [], [], 0
    out_tokens = 0
    for status, r in measured:
        t = r["info"]["timings"]
        empty = workload == "interactive" and not (r.get("output") or "").strip()
        if status != "successful" or empty:
            failed += 1
            continue
        ttft.append(r["time_to_first_token_ms"] / 1000)
        if r.get("time_to_first_output_token_ms") is not None:
            visible.append(r["time_to_first_output_token_ms"] / 1000)
        first, last = t.get("first_token_iteration"), t.get("last_token_iteration")
        if first and last and last > first and r["output_tokens"] > 1:
            gen.append((r["output_tokens"] - 1) / (last - first))
        total.append(r["request_latency"])
        out_tokens += r["output_tokens"] or 0

    window = (measured[0][1]["request_start_time"], max(r["request_end_time"] for _, r in measured)) if measured else (0, 0)
    span = window[1] - window[0]
    stats = {
        "workload": workload, "streams": streams, "label": os.path.basename(path)[:-5],
        "n": len(measured), "ok": len(total), "fail": failed,
        "ttft": ttft, "visible": visible, "gen": gen, "total": total,
        "tput": out_tokens / span if span > 0 else None,
    }
    stats.update(server_counters(path[:-5] + ".metrics.csv", window))
    stats["overlap"] = overlap_split(path[:-5] + ".overlap.json", measured)
    return stats


def overlap_split(overlap_path, measured):
    """For the interference level: requests that overlapped the long read vs not."""
    if not os.path.exists(overlap_path):
        return None
    o = json.load(open(overlap_path))
    groups = {"during": [], "outside": []}
    for status, r in measured:
        if status != "successful":
            continue
        hit = r["request_start_time"] < o["end"] and r["request_end_time"] > o["start"]
        groups["during" if hit else "outside"].append(r)
    summary = {"long_request": o["metrics"], "found_all_4_rejections": o.get("found_all_4_rejections")}
    for name, rs in groups.items():
        vis = [r["time_to_first_output_token_ms"] / 1000 for r in rs if r.get("time_to_first_output_token_ms")]
        tot = [r["request_latency"] for r in rs]
        summary[name] = {"n": len(rs), "visible_p50": pct(vis, 50), "visible_p95": pct(vis, 95),
                         "total_p50": pct(tot, 50), "total_p95": pct(tot, 95)}
    return summary


def server_counters(csv_path, window):
    """Peaks (and counter increases) of the sampler's rows inside the measured window."""
    if not os.path.exists(csv_path):
        return {"run": None, "wait": None, "kv": None, "preempt": None, "prefix_hit": None}
    rows = [r for r in csv.DictReader(open(csv_path))
            if window[0] <= float(r["time"]) <= window[1]]
    col = lambda name: [float(r[name]) for r in rows if r.get(name) not in (None, "")]
    delta = lambda name: (col(name)[-1] - col(name)[0]) if len(col(name)) > 1 else None
    hits, queries = delta("prefix_hits"), delta("prefix_queries")
    return {
        "run": max(col("running"), default=None),
        "wait": max(col("waiting"), default=None),
        "kv": max(col("kv_usage"), default=None),
        "preempt": delta("preemptions"),
        "prefix_hit": hits / queries if hits is not None and queries else None,
    }


def verdict(s):
    t = TARGETS.get(s["workload"])
    if not t or s["n"] == 0:
        return "-"
    fail_rate = s["fail"] / s["n"]
    checks = [fail_rate <= t["fail_rate"]]
    if "visible_p95_s" in t:
        checks.append((pct(s["visible"], 95) or math.inf) <= t["visible_p95_s"])
        checks.append((pct(s["gen"], 5) or 0) >= t["gen_p95_tok_s"])  # 95% of requests at least this fast
    if "total_p95_s" in t:
        checks.append((pct(s["total"], 95) or math.inf) <= t["total_p95_s"])
    word = "USABLE" if all(checks) else "no"
    return word + (" SHORT" if s["ok"] < MIN_SAMPLES else "")


def fmt(v, digits=1):
    return "-" if v is None else f"{v:.{digits}f}"


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(HERE, "results", "*")))[-1]
    levels = [level_stats(p) for p in sorted(glob.glob(os.path.join(folder, "*.json")))
              if not p.endswith(".overlap.json")]
    if not levels:
        sys.exit(f"no results in {folder}")
    for workload in sorted({s["workload"] for s in levels}):
        rows = sorted((s for s in levels if s["workload"] == workload), key=lambda s: (s["streams"], s["label"]))
        print(f"\n## {workload}   targets: {TARGETS.get(workload, 'none')}\n")
        print("| level | N | measured | ttft p50/p95 s | visible p50/p95 s | gen p50/p5 tok/s | total p50/p95 s "
              "| tput tok/s | fail | run | wait | kv | preempt | verdict |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s in rows:
            print(f"| {s['label']} | {s['streams']} | {s['ok']}/{s['n']} "
                  f"| {fmt(pct(s['ttft'], 50))} / {fmt(pct(s['ttft'], 95))} "
                  f"| {fmt(pct(s['visible'], 50))} / {fmt(pct(s['visible'], 95))} "
                  f"| {fmt(pct(s['gen'], 50))} / {fmt(pct(s['gen'], 5))} "
                  f"| {fmt(pct(s['total'], 50))} / {fmt(pct(s['total'], 95))} "
                  f"| {fmt(s['tput'], 0)} | {s['fail']} | {fmt(s['run'], 0)} | {fmt(s['wait'], 0)} "
                  f"| {fmt(s['kv'], 2)} | {fmt(s['preempt'], 0)} | {verdict(s)} |")
    for s in levels:
        if s.get("overlap"):
            o = s["overlap"]
            lr = o["long_request"]
            print(f"\n## {s['label']}: one {lr.get('prompt_tokens')}-token document among {s['streams']} users")
            print(f"long request: first token {fmt(lr.get('ttft_s'))} s, total {fmt(lr.get('total_s'))} s, "
                  f"all 4 rejections found: {o['found_all_4_rejections']}")
            for name in ("outside", "during"):
                g = o[name]
                print(f"  {name:8} its read: n={g['n']:3}  visible p50/p95 {fmt(g['visible_p50'])} / {fmt(g['visible_p95'])} s"
                      f"  total p50/p95 {fmt(g['total_p50'])} / {fmt(g['total_p95'])} s")
    print("\ngen p5 = the speed 95% of requests met or beat. kv = peak KV-cache use (0-1). "
          "preempt = preemptions during the measured window.")


if __name__ == "__main__":
    main()
