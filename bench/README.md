# bench/ — how many people can use the deployment at once

A load test for the Qwen3.8-27B endpoint, built on
[GuideLLM](https://github.com/vllm-project/guidellm). It keeps N requests in
flight at a time and records how the answers slow down as N grows, together
with the server's own counters, so every slowdown can be explained.

| File | What it is |
|---|---|
| `make_datasets.py` | builds `datasets/interactive.json`: the 12 real coding and report prompts from `eval/tasks.md` |
| `run.sh` | runs **one level**: one workload at one concurrency |
| `metrics_sampler.py` | records vLLM's `/metrics` every 5 s during a level (`run.sh` starts it for you) |
| `summarize.py` | turns a results folder into one table per workload and judges each level |
| `tests/test_sampler.py` | checks the sampler with a fake server; no GPU needed |
| `results/<date>/` | what each run wrote: `<label>.json`, `<label>.metrics.csv`, `<label>.log` |

## Install (once)

GuideLLM needs torch and transformers, so it lives in its own environment.
CPU-only torch keeps the download to about 1.6 GB; the load test never uses a
local GPU.

```bash
python3 -m venv bench/.venv
bench/.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
bench/.venv/bin/pip install "guidellm[recommended]==0.7.4"
python3 bench/make_datasets.py
```

## Try it for free first, against GuideLLM's mock server

The mock server imitates an OpenAI endpoint on your laptop: 200 ms to the first
token, 10 ms per token. It is how every script here was tested, and it costs
nothing.

```bash
bench/.venv/bin/guidellm mock-server --host 127.0.0.1 --port 8123 \
    --model Qwen/Qwen3.8-27B-FP8 --ttft-ms 200 --itl-ms 10 --output-tokens 150 &
BENCH_API_KEY=dummy MODAL_PROXY_TOKEN=unused \
    bench/run.sh interactive 4 --target http://127.0.0.1:8123 --no-sampler --label mock-interactive-4
python3 bench/summarize.py
kill %1
```

Don't pass `--processor` to the mock server: GuideLLM 0.7.4 loads it with a
tokenizer class that fails on Qwen's tokenizer. Real runs are unaffected.

## A real run

**The endpoint must be warm first.** `run.sh` and the sampler both send
requests, and a request to a sleeping endpoint starts a GPU container. Warm it
with one request, wait for a 200, then:

```bash
bench/run.sh interactive 8          # 8 requests in flight, real prompts
bench/run.sh agent 4                # coding-agent shape: 16K shared context, 300-token steps
bench/run.sh interactive 8 --label interactive-8-repeat   # same level again, for noise
python3 bench/summarize.py
```

`run.sh` reads `MODAL_PROXY_TOKEN` from `.env` and passes it to GuideLLM at run
time. GuideLLM saves it masked (`**********`) in its results, but scan
`bench/results/` for the token before committing anyway.

**Keep concurrency at or below 30.** One container takes 32 requests at once,
and the sampler uses one of them. With `max_containers=1`, anything over the
limit waits in a queue, which would distort the very level being measured.

## What each level does

- **N requests always in flight.** As one finishes the next starts: a room of N people who are never idle. The worst case, by design.
- **Runs until `max(20, 3N)` requests are measured, or 4 minutes.** `summarize.py` drops the first and last 10% of requests (start-up and wind-down), so `run.sh` sends a few more than it measures. A level cut short by the 4-minute cap is flagged `SHORT`.
- **Temperature 0,** so two configurations (e.g. MTP on and off) generate the same tokens and compare like for like.
- **Interactive** answers stop naturally, capped at 4,000 tokens. **Agent** steps are forced to exactly 300 tokens.

## Reading the summary

| Column | Meaning |
|---|---|
| `ttft` | time to first token, thinking included |
| `visible` | time to first **visible** token: what a person actually waits for |
| `gen` | generation speed per request: (tokens − 1) / (last token − first token), the same formula as `eval/decode_bench.py`. `p5` is the speed 95% of requests met or beat |
| `total` | whole request time |
| `tput` | output tokens per second across every request at that level |
| `fail` | errored, incomplete, or (interactive) an empty answer. Failures stay in the count |
| `run`, `wait` | peak requests running / queued inside vLLM |
| `kv` | peak share of the KV cache in use (0–1) |
| `preempt` | requests evicted to free memory during the level |

Why a level is slow:
- `wait > 0`: requests queued.
- `kv` near 1 with `preempt > 0`: out of memory.
- Neither: the GPU is simply busy (compute-bound).

**Verdict** applies the targets fixed in the design *before* any results
existed:
- **Interactive:** p95 time to first visible token at most 20 s, 95% of requests generating at least 15 tok/s, at most 1% failed.
- **Agent:** p95 time per request at most 20 s.

To judge against different targets, edit `TARGETS` in `summarize.py`. The raw
results don't change.

## Metric names on this server

`metrics_sampler.py` matches vLLM's metric names by pattern, because they
change between vLLM versions. The names this deployment actually exports are
recorded here after the first real scrape:

Recorded from the first real scrape, 2026-09-29 (vLLM 0.30.0, FP8 KV):

| Column | vLLM metric |
|---|---|
| `running` | `vllm:num_requests_running` |
| `waiting` | `vllm:num_requests_waiting` |
| `kv_usage` | `vllm:kv_cache_usage_perc` |
| `preemptions` | `vllm:num_preemptions_total` |
| `prefix_hits` / `prefix_queries` | `vllm:prefix_cache_hits_total` / `vllm:prefix_cache_queries_total` |
| `gen_tokens` | `vllm:generation_tokens_total` |

The `/metrics` endpoint is reachable through the same authenticated URL as the API.
