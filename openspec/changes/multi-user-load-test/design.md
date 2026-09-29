# Design

## Context

See `proposal.md` for why; requirements are in `specs/multi-user-capacity`.

**Serving configuration today** (`deploy.py`, one A100-80GB):

```
max-model-len 250,000   kv-cache-dtype bfloat16   MTP num_speculative_tokens=3
reasoning_effort low    @modal.concurrent(max_inputs=32)   no max_containers
idle window 10 min
```

**What is already measured**, all one request at a time unless stated:

| Measurement | Value | Source |
|---|---|---|
| Decode, short prompt, MTP on | 112.7 tok/s (spread 1.1) | phase 2, `eval/decode-mtp.txt` |
| Decode, short prompt, MTP off | 49.3 tok/s | phase 2, `eval/decode-baseline.txt` |
| Decode at 75K / 137K / 195K context | 36–41 / 29 / 21 tok/s | phase 2 eval `summary.json` |
| Cold first read, 137K tokens | 71 s (cached: 3.4 s) | phase 2 eval |
| Typical interactive task, total | 5–22 s, ~11 s average | phase 2 eval, coding and report tasks |
| Two concurrent requests | ~83 tok/s combined (MTP off, FP8 KV, 128K) | phase 1 |
| KV pool | ~42 GiB: ~690K tokens at BF16, ~1.4M at FP8 | phase 2 startup log |

**GuideLLM 0.7.4, verified by reading its source** (not assumed from docs):

- Sends bearer-token auth (`api_key`), so the Modal proxy token works as it is.
- Reads thinking from both `reasoning` (vLLM) and `reasoning_content` (LiteLLM), and records **time to first output token (TTFOT)**: the first *non-reasoning* token, separately from TTFT.
- Offers a `concurrent` profile (`streams=N`) with `warmup`/`cooldown`, plus `max_duration` and `max_errors` constraints.
- Supports synthetic data with `prefix_tokens`/`prefix_count` (a shared context across requests), and `json_file` data for real prompts.
- Sets `max_tokens` **and `ignore_eos`** when a dataset specifies output length. With a plain `max_tokens` it lets the model stop naturally.
- Depends on torch and transformers.
- Takes the API key only as a command argument; there is no environment variable for it.

**Budget:** $8.66 read after phase 2's evaluation, less the ~$0.50 LiteLLM check, so about **$8.10**. Ceiling for this change: **$4**. The balance can only be read from the Modal dashboard, so gates depend on the operator reporting it.

## Goals / Non-Goals

**Goals:**

- One measured capacity curve per workload on the configuration users will get, with the server-side reason for every knee.
- A load test anyone on the team can re-run with two commands.

**Non-Goals:**

- **Tuning batching** (`--max-num-batched-tokens`, `--max-num-seqs`). That's the operator's next lever, and this change supplies the baseline to judge it.
- **Raising `max_inputs` above 32 or adding GPUs.** If capacity reaches the top tested level, that is recorded as "at least", and raising the limit becomes the next test.
- **Testing through LiteLLM.** Gateway parity was proven byte-for-byte in phase 2. Routing load through the laptop's gateway would add the laptop as a variable.
- **Images under load.** An image request is ~1–2K prompt tokens and behaves like a short text prompt; the vision *quality* result stands from phase 2.
- **`medium` effort under load.** Everything runs at the default `low`. Phase 2 measured `medium` at +43% reasoning tokens, so capacity at `medium` can be estimated from these results without a separate run.
- **Measuring how often real users send requests.** That needs real usage logs from a pilot. Here it is an explicit assumption.

## Decisions

### Change the configuration first, then measure

The test measures `KV_CACHE_DTYPE = "fp8"` with `max_containers=1`, not today's evaluation setup.

- **FP8** doubles the KV pool to ~1.4M tokens. That matters when several people send long prompts: agents and documents.
- **`max_containers=1`** makes the load test honest. Beyond one container's 32 slots, requests queue on the GPU being measured instead of Modal quietly starting a second A100 and blurring the result.

The FP8 change carries a known risk: phase 2 chose BF16 because a community benchmark showed FP8 losing accuracy at 256K. So the first work on the new container re-runs the six long-document tasks at the default effort, graded with the same criteria and checks, against the retained BF16 answers. The spec decides what happens if accuracy drops. Answers will not be byte-identical, because FP8 changes the arithmetic, so grading is against the criteria, not by text comparison.

*Alternative considered:* measuring BF16 as well. Rejected on cost: a second full sweep for a configuration nobody intends to serve many users on.

### GuideLLM, validated against our own benchmark

*Alternatives considered:*

- `vllm bench serve` needs a full local vLLM install with CUDA wheels, heavier than GuideLLM, and has no TTFOT measure.
- A new script of our own would re-implement percentile maths, load profiles and reports that GuideLLM already has and has tested.

GuideLLM measures TTFOT natively, which is the metric that matters with thinking on.

Its cost is the torch/transformers dependency. It is installed in its own git-ignored virtual environment, `bench/.venv`, with CPU-only torch to keep the download small. None of it touches `deploy.py` or `eval/`.

**Validation is the gate** (spec: "The measurement method is validated"). On a warm container, GuideLLM runs the `decode_bench.py` prompt one request at a time and must match that script within 10% on TTFT and generation speed. **Fallback:** if it can't be installed or doesn't match, a small standard-library script replaces it, reusing the streaming logic already proven in `eval/run_eval.py` (which separates reasoning the same way).

### Closed-loop concurrency levels, not request rates

Each level keeps exactly N requests in flight (`concurrent`, `streams=N`); as one finishes, the next starts. That is a room of N people who are *always* waiting for an answer, which is the worst case. It measures capacity in concurrent requests directly.

*Alternative:* arrival-rate profiles (`poisson`, `constant`). Rejected because the right rate depends on how often real people send requests, which is exactly what is unknown. Concurrency is measured instead, and turned into users afterwards with stated assumptions (see below).

**Levels:**

- **Interactive:** 1, 4, 8, 16, 30.
- **Agent:** 1, 4, 8.
- **Interference:** runs at 8.

The top level is 30, not 32. The server-counter sampler (below) also occupies one of the container's 32 slots, and with `max_containers=1` a 33rd input would queue. That would silently delay the sampler, or a test request, at exactly the level where timing matters most.

**Length of each level:** 10% warmup and cooldown, then run until at least `max(20, 3×N)` requests complete, with a 4-minute cap. Twenty is the minimum sample that makes a 95th percentile mean anything. A level cut off by the cap before 20 is flagged in the results, not quietly reported.

**Noise:** the interactive level at 8 runs twice, and the difference between the two runs is the run-to-run noise. The MTP decision and any "A is faster than B" claim must beat it.

### Three workloads

| Workload | Data | Why this shape |
|---|---|---|
| **Interactive** | The 12 coding and report prompts from `eval/tasks.md`, as a JSON file; `max_tokens` 4,000; natural stopping | Real prompts produce real thinking lengths, which is what drives time to first visible token. Synthetic text with `ignore_eos` would make thinking length arbitrary |
| **Agent** | Synthetic: a 16,000-token prefix shared by all requests, 1,000 unique tokens each, 300 output tokens | Coding agents resend a large context and ask for short steps. The shared prefix is deliberate: it exercises the prefix cache the way real agents do |
| **Interference** | Interactive at 8 streams, plus one 137K-token long-document request sent from a separate process mid-run | One person dropping a big document into a busy room. The document gets a unique first line so the prefix cache (warm from the accuracy re-check) cannot serve it |

Only 12 interactive prompts are cycled, so repeats will hit the prefix cache. At 200–700 prompt tokens, prefill is a fraction of a second either way, and generation dominates. That is recorded as a known, negligible bias.

### Record the server's own counters

A small sampler polls vLLM's Prometheus `/metrics` through the same authenticated URL every 5 seconds during every run, writing timestamped rows: requests running, requests waiting, KV cache use, and preemptions total. Metric names differ between vLLM versions, so they are read from the first scrape, not hard-coded. This is what lets each knee be attributed (spec: "Slowdowns are explained"):

- `waiting > 0` means queueing.
- KV cache near 100%, together with preemptions, means memory.
- Neither means compute-bound.

### "Usable" is fixed now, before any result exists

These defaults are recorded here so they predate the results; the operator may change them before apply. All results are retained, so any other target can be applied later.

| Workload | Usable at a level if all hold |
|---|---|
| Interactive | p95 time to first **visible** token ≤ 20 s; p95 per-request generation ≥ 15 tok/s; failed requests ≤ 1% |
| Agent | p95 time per request ≤ 20 s; failed ≤ 1% |

Reasoning behind the numbers:

- **15 tok/s** is about twice reading speed, so a streaming answer never appears to stall.
- **20 s to the first visible word** allows a 3–4× slowdown over today's single-request ~5 s, before people start giving up.
- **Agent steps:** phase 1's usable-but-slow agent sessions averaged 10–19 s per request, so 20 s per step keeps a 60-step task near 20 minutes.

### From concurrent requests to users

```
users supported  =  capacity (concurrent requests meeting the target)
                    -------------------------------------------------
                       fraction of time each user has a request in flight
```

Busy-fraction assumptions, stated in the findings next to every user number:

- **Interactive users:** 10% and 20%, i.e. one ~15 s request every 75–150 s of active use.
- **Agent users:** 100% while their agent runs.

No single blended number is given. The findings show a small table for a mixed team instead.

### MTP under load: a second, gated window

MTP's 2.29× was one request with a mostly idle GPU. As batches grow, the spare compute that verifies draft tokens disappears, so the gain may shrink or reverse.

Window 2 redeploys FP8 **without** MTP and repeats the interactive levels 8 and 30. MTP is kept only if, at the level nearest measured capacity, it is at least as good as off by more than the noise measured at 8. Window 2 runs only if the balance after window 1 leaves it inside the ceiling.

### Cut the idle tail

The 10-minute idle window after each test costs ~$0.50 and measures nothing. So at the end of each window: `modal app stop`, then `modal deploy` immediately. Stop alone would undeploy the endpoint (the phase-1 lesson); the pair releases the GPU at once and leaves the endpoint up, with no container until the next request.

### Cost plan

| Window | Contents | GPU time | Cost |
|---|---|---|---|
| 1 (FP8, MTP on) | cold start (~10 min, first start of a new config) → accuracy re-check (~10 min) → validation (~3 min) → interactive 5 levels + one repeat (~20 min) → agent 3 levels (~9 min) → interference (~5 min) | ~57 min | ~$2.80 |
| 2 (FP8, MTP off), gated | cold start (~7 min) → interactive at 8 and 30 (~7 min) | ~14 min | ~$0.70 |
| **Total** | | | **~$3.50** under the $4 ceiling |

## Risks / Trade-offs

- **FP8 loses long-document accuracy** → Checked before anything else. If it drops, the spec forces an explicit decision: keep BF16 and accept half the KV room, or keep FP8 and document the loss per task. A BF16 fallback costs one more cold start (~$0.50), within the ceiling.
- **GuideLLM measures something different from what we think** → The 10% validation gate against `decode_bench.py` before any load run; the fallback script is already half-written in `run_eval.py`.
- **The API key leaks** → Passed from `.env` by the wrapper at run time, never written to committed files. GuideLLM keeps it as a pydantic `SecretStr`, which should serialize masked; that is not assumed, and results are scanned for the token before every commit, as in phases 1–2. The key is briefly visible in the local process list during a run, which is acceptable on a single-user laptop.
- **Modal's edge fails under load** (phase 1 once produced "Server has lost track of input") → Failures are counted, not dropped (spec), and matched against `modal app logs` to tell platform errors from model errors.
- **Someone else uses the endpoint during a window** → Their requests would distort the results. Windows are announced to the team, and the sampler's `running` counter shows extra traffic.
- **Twelve repeated prompts are not the whole of real use** → They cover real coding and report work with real thinking lengths; the agent and interference workloads cover the rest. Findings state that real usage traces from a pilot would replace them.
- **The 20 s / 15 tok/s target is a judgement** → It is stated before results and the raw curves are retained, so a different target changes the capacity number without a re-run.
- **The balance can't be read automatically** → Gates stop and ask the operator for the dashboard figure before each window.

## Migration Plan

1. Change `deploy.py`: `KV_CACHE_DTYPE = "fp8"` (updating the comment that explains the BF16 choice), and `max_containers=1` on `serve()` with a comment. Redeploy with stop and deploy.
2. After the MTP decision, set `SPECULATIVE_CONFIG` accordingly and redeploy the final configuration.
3. **Rollback:** restore the previous values in `deploy.py` and redeploy. The endpoint URL and API do not change, and nothing is migrated.

## Open Questions

- **Exact vLLM Prometheus metric names in the installed version.** Read from the first scrape; this doesn't change the approach.
- **Whether GuideLLM's `concurrent` profile accepts several stream counts in one invocation.** If not, one invocation per level; this changes nothing else.
