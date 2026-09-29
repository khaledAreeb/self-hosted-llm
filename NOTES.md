# Pilot log — Qwen3.8-27B on Modal

Running record of budget, measurements, and decisions made during the pilot.
Every figure here must come from an observed source (Modal billing dashboard,
a timed request, an exported log) — never from an estimate.

## Budget baseline

| Date | Event | Balance | Source |
|---|---|---|---|
| 2026-09-24 | Pilot start | **$30.00** | Modal dashboard, `dev-khaled-areeb`, Starter plan |

Workspace: `dev-khaled-areeb` (Starter plan, $30/month included compute).

At roughly **$2.54/hr effective** on A100-40GB — $2.10/hr GPU plus ~$0.44/hr for
the separately-billed 4 CPU cores and 32 GiB of memory — $30 buys about
**11.8 GPU-hours** in total. The CPU/memory additivity is inferred from Modal's
pricing page listing them as separate line items and should be confirmed against
the first real invoice.

## Spend log

| Date | Activity | Cost | Balance after | Source |
|---|---|---|---|---|
| 2026-09-24 | Image build + first download attempt (CPU only, ~90s) | **$0.03** | $29.97 | Modal dashboard |
| 2026-09-24 | Group 3 balance check (task 3.1), above the $25 halt threshold | — | $29.97 | Modal dashboard |
| 2026-09-24 | Stage 1 + gateway verification complete (tasks 4.1, 5.1) | **$2.58 cumulative** | **$27.42** | Modal dashboard |
| 2026-09-25 | Phase 1 close: snapshot experiment, Copilot/OpenCode integration, agent-load testing | **$13.85 cumulative** | **$16.15** | Modal dashboard |
| 2026-09-27 | **Phase 2 baseline** (task 1.1) — capability evaluation begins | — | **$16.15** | Modal dashboard |
| 2026-09-28 | Group 3 gate (task 3.1) — after 250K memory test, `bf16` crash loop, long-context tests | **$2.76 this phase** | **$13.39** | Modal dashboard |
| 2026-09-28 | Group 5 gate (task 5.1) — after decode baseline, MTP test, `low` verification (three cold starts) | **$4.95 this phase** | **$11.20** | Modal dashboard |
| 2026-09-28 | After the evaluation run (task 6.6) — two passes, repeats, one cold start | **$7.49 this phase** | **$8.66** | Modal dashboard |
| 2026-09-29 | **Phase 3 start** and window-1 gate (task 3.1). Phase 3 ceiling $4, window 1 needs ~$2.80: pass | — | **$7.85** | Modal dashboard |

**Phase 2 budget reality.** $16.15 remains against an original $30. The cost
pilot alone needs roughly $20.60 (about 7 GPU-hours at ~$2.94/hr), so **the
original budget can no longer fund both this evaluation and the pilot**.

Capability evaluation takes priority, with the ceiling raised from $8 to $12.
The reasoning is ordering rather than preference: if the model is not good
enough, its running cost is irrelevant, and quality evidence is what justifies
requesting more budget. A cost forecast for a model nobody has judged persuades
no one.

Where the $13.85 went: cold starts dominate. Roughly $3.90 on the GPU memory
snapshot experiment that was measured and reverted, and most of the rest on
cold starts triggered while debugging the Copilot and OpenCode integrations —
each failed attempt woke the GPU.

**Spend to date: $2.58 of $30.00.** At ~$2.94/hr effective on A100-80GB that
leaves roughly **9.3 GPU-hours**, comfortably above the 7-hour floor task 5.1
requires for the team trial.

Where the $2.58 went: four cold starts at ~7-10 minutes each dominate it. The
28 GB download cost $0.03, and every authentication test cost nothing because
Modal rejects at its edge. Cold starts are the only meaningful expense so far,
which is what makes the stage 4 memory-snapshot work worth considering.

The download step costs about **$0.03**, not the $1-2 that was estimated before
the first run. The estimate was roughly 50x too high: the work is CPU-only, the
image build is cached after the first time, and 28 GB over a datacenter link
takes about 90 seconds. Downloads are effectively free at this scale — GPU time
is the only cost that matters to this budget.

## Measurements

| Metric | Value | How measured |
|---|---|---|
| Cold start, unoptimized (3.10) | **602 s** (~10 min) | Timed from request to first HTTP 200, A100-80GB, 2026-09-24 |
| Weight load from Volume | 18.13 s | vLLM log |
| Warmup/profiling | 105.25 s | vLLM log |
| Warm round trip | 2.11 s for 54 tokens | Smoke test, non-streamed |
| **Repeat cold start** (compilation cached) | **514 s** | Timed 2026-09-24, A100-80GB |
| Cold start, with snapshots (6.3) | | |
| **Warm TTFT (5.4)** | **0.62 s** | `time_starttransfer` on a streamed request |
| **Warm output tok/s (5.4)** | **44.5 tok/s** | 800 completion tokens in 17.96 s, non-streamed |
| Duty cycle (5.8) | | |
| Effective $/M output tokens (5.10) | | |

**Endpoint:** `https://dev-khaled-areeb--qwen38-27b-serve.modal.run`
**GPU:** A100-80GB · **vLLM:** 0.30.0 · **Model:** `Qwen/Qwen3.8-27B-FP8`

### The 602 s cold start is the *first-ever* one

It includes work that should not repeat: `torch.compile` (Dynamo bytecode
transform ~19 s) and CUDA graph capture, both written into the `vllm_cache`
Volume. Subsequent cold starts should be materially faster. Task 4.4 must set
the LiteLLM timeout above the *measured repeat* cold start, not this number —
but until a repeat is measured, 602 s is the only evidence available, and a
timeout below it would fail a request while the backend was starting normally.

### Reasoning tokens dominate output

The smoke test asked for "exactly one short sentence". The response:

| | Tokens |
|---|---|
| Prompt | 63 |
| **Reasoning** | **47** |
| Visible answer | 7 |
| Total completion | 54 |

**87% of generated tokens were reasoning**, for a trivial request. The
`--reasoning-parser qwen3` flag works correctly — reasoning arrives in a
separate `reasoning` field rather than polluting `content`, in both
non-streamed and streamed responses.

But the cost implication is real: every response pays a large thinking
overhead, and users wait through it. At the observed round-trip rate this
means a noticeably slower experience than the raw decode rate suggests. The
pilot should decide deliberately whether thinking stays on by default; the
evaluation set in task 5.2 should include both modes.

Do **not** treat 54 tokens / 2.11 s as the decode rate — that figure includes
prefill and network round trip. Task 5.4 measures TTFT and sustained tok/s
properly.

### 2026-09-24 — BLOCKER: default reasoning effort is `xhigh`, answers come back empty

Two substantive requests were measured. **Both returned zero visible content.**

| Request | max_tokens | reasoning tokens | visible tokens | finish_reason |
|---|---|---|---|---|
| "detailed 400-word explanation" | 800 | **800** | **0** | `length` |
| "150-word paragraph" (streamed) | 400 | **400** (400 chunks) | **0** (0 chunks) | — |

`content` was `None`. The model exhausted the entire token budget thinking and
never began its answer. The reasoning trace shows it counting words one at a
time — `"14 inventory 15 data 16 to 17 identify..."` — to hit the requested
word count.

Cause: this model defaults to **`xhigh` reasoning effort**. It is not a bug and
not a quantization artifact; it is the shipped default.

As configured, any user asking a substantive question with a normal token limit
receives an empty response. This must be resolved before the team touches it.

Controls available (vLLM `chat_template_kwargs`, server-wide via
`--default-chat-template-kwargs`, overridable per request):

| Setting | Effect |
|---|---|
| `{"enable_thinking": false}` | no reasoning at all, direct answers |
| `{"reasoning_effort": "low"}` | reasoning kept, far smaller budget |
| `{"reasoning_effort": "medium"}` | middle ground |
| *(unset)* | `xhigh` — current behaviour |

`--reasoning-parser qwen3` is separate and should stay: it keeps reasoning out
of `content` and makes the token accounting above visible at all. Without it,
this failure would have looked like rambling answers rather than empty ones.

### 2026-09-24 — RESOLVED: `enable_thinking: false` set server-side

Added `--default-chat-template-kwargs '{"enable_thinking": false}'` to the vLLM
command in `deploy.py`. The identical request, re-run:

| | Before | After |
|---|---|---|
| `finish_reason` | `length` | **`stop`** |
| completion tokens | 800 | 578 |
| reasoning tokens | **800** | **0** |
| visible tokens | **0** | **578** |
| `content` | `None` | **3,257 characters** |

The answer is coherent and domain-appropriate, opening: *"Warehouse inventory
reconciliation is a critical operational process that ensures the physical stock
on hand matches the digital records maintained in the Warehouse Management
System (WMS)..."*

Streamed request: **205 content chunks, 0 reasoning chunks** — against 400
reasoning chunks and 0 content chunks before.

Set on the vLLM side rather than in LiteLLM because `chat_template_kwargs` is a
vLLM extension rather than part of the OpenAI spec. Routing it through a proxy
would mean depending on that proxy to forward a non-standard field — the same
bet that failed with Modal's auth headers in BerriAI/litellm#11021. Setting it
at the source also covers callers that bypass the gateway entirely.

Per-request override remains available and always wins over the server default:
`{"chat_template_kwargs": {"enable_thinking": true}}`.

### Latency, once the answer budget is fixed

| Metric | Thinking on (`xhigh`) | Thinking off |
|---|---|---|
| TTFT (warm) | 0.62 s *(to first reasoning token)* | **1.56 s** *(to first real word)* |
| Sustained decode | 44.5 tok/s | ~33-41 tok/s |
| Streamed chunks | 402, **all reasoning** | 205, **all content** |
| Visible output | **none** | the full answer |

Raw throughput is broadly similar; what changed is what the throughput buys.
Before, ~43 tok/s of internal monologue reached the user as an empty response.
Now the same machine delivers visible words. TTFT rose from 0.62 s to 1.56 s
only because the earlier figure timed the first *reasoning* token — previously
there was no time-to-first-real-word at all, because no real word ever arrived.

33-41 tok/s sits below the ~51 tok/s predicted for A100-80GB but roughly double
what an L40S would have given, so the speed argument behind the GPU choice
holds. Measure again with the task 5.2 evaluation set before quoting a number
externally; a single prompt is not a benchmark.

### Cold starts are trending down

| Attempt | Duration |
|---|---|
| First ever (torch.compile + graph capture) | 602 s |
| Second | 514 s |
| Third | **428 s** |

Roughly 7.1 minutes and still falling as the `vllm_cache` Volume fills. Task
4.4's 900 s timeout stays comfortably above it. Worth re-checking after a few
more starts before lowering that timeout.

### Repeat cold start: 514 s, only 15% better than the first

| | Duration |
|---|---|
| First-ever cold start | 602 s |
| Repeat, compilation cached | **514 s** |

The `vllm_cache` Volume saves about 88 seconds — far less than hoped. Cold
starts cost ~8.5 minutes regardless, which makes two things concrete:
the LiteLLM timeout in task 4.4 must stay well above 514 s, and stage 4's
memory snapshots become considerably more attractive than "optional".

## Decisions and deviations

**2026-09-24 — Proxy tokens are held by the caller, not the deployment.**
Task 1.3 originally said to store the token pair in a Modal Secret. That was
wrong: Modal validates proxy tokens at its own edge, so the container never sees
them and a Modal Secret would serve no purpose. The pair is stored instead as the
combined bearer form in a gitignored `.env` locally, and as an environment
variable on the LiteLLM host. Token `litellm-qwen` (`wk-65dTBzFjfs1NS49q0t2oVV`)
created for the gateway; create a second token for operator testing so either can
be revoked independently.

**2026-09-24 — LiteLLM needs no custom-header support.**
Modal accepts the proxy token pair as a single standard
`Authorization: Bearer wk-<id>.ws-<secret>` header, which is what LiteLLM already
sends for any OpenAI-compatible provider. This removes the dependency on
`extra_headers` and sidesteps BerriAI/litellm#11021, which was closed as not
planned.

**2026-09-24 — Hugging Face Xet backend silently broke the weight cache.**
The first download reported success (81/81 files, exit 0) but left only ~10 MB
of real bytes in the Volume. With Xet enabled, `blobs/` is populated with
79-byte symlinks into a content-addressed chunk cache that does not survive the
Volume commit — 67 of 81 blobs were links, and `xet/` held only `staging/` and
`logs/`. The snapshot looked complete while the weights were absent, which would
have shown up later as a mysteriously slow and expensive first request, because
every cold start would re-download 28 GB.

Fixed by setting `HF_HUB_DISABLE_XET=1` in the image, forcing the classic HTTP
path. Relative symlinks *inside* `snapshots/` do persist correctly, so only the
Xet indirection was at fault. Caught because task 2.4 required evidence from
`modal volume ls` rather than trusting the exit code.

A second lesson came from the retry: with the fix in place the download still
took **0.0 seconds** and changed nothing, because `snapshot_download` saw 81
filenames already present and treated the cache as complete. A cache that is
wrong but complete-looking is invisible to the tool that wrote it. The stale
`hub/models--Qwen--Qwen3.8-27B-FP8` and `xet/` directories had to be deleted
before the fix could take effect.

Verified after the clean re-download: **28.78 GiB across 81 entries, every one
of type `file`, 66 of them larger than 100 MB.** Download pace is itself the
tell — the broken run finished 81 files in 90 seconds because nothing was
transferred, while the correct run took about 6 minutes.

`HF_HUB_ENABLE_HF_TRANSFER` was also removed: `huggingface_hub` 1.32 warns it is
deprecated and no longer used.

**2026-09-24 — Edge auth verified, and it is measurably free.**
Endpoint: `https://dev-khaled-areeb--qwen38-27b-serve.modal.run` (deployed with
the key marker, confirming proxy auth is active). Two rejection paths tested
against a scaled-to-zero deployment:

| Request | Status | Response time | Body |
|---|---|---|---|
| No credentials | 401 | 0.494 s | `modal-http: missing credentials for proxy authorization` |
| Invalid credentials | 401 | 0.487 s | `modal-http: invalid credentials for proxy authorization` |

`modal container list` showed zero active containers afterwards. Half-second
responses are orders of magnitude too fast for a container start, so rejected
traffic genuinely costs nothing no matter its volume.

The two distinct messages are the diagnostic that task 4.2a depends on:
`missing` means the caller never sent credentials (LiteLLM dropped them), while
`invalid` means they arrived but were wrong (LiteLLM forwards correctly). That
distinction can be read at zero GPU cost.

**2026-09-24 — Scale-to-zero verified.**
Last request at 12:12:02; the container was gone **284 s later**, consistent
with the 300 s idle window. GPU billing stops at that point, which is the
property the whole cost model rests on: outside working hours the deployment
costs nothing, and the only idle cost is the window between bursts *inside* a
working day.

**2026-09-24 — A100-40GB OOM, switched to A100-80GB.**
The first serving attempt died with `torch.OutOfMemoryError` during KV cache
profiling: 30.13 GiB already resident, 12.25 GiB requested, 39.49 GiB total.
The design's memory arithmetic was wrong — see *Corrected memory model* in
`design.md`. Root cause is allocation granularity, not per-token size: vLLM
inflates the attention block to 1568 tokens to match the Gated DeltaNet page
size, so the minimum KV allocation is 12.25 GiB.

L40S was the pre-selected fallback but offers only ~0.8 GiB of margin against
the measured 42.4 GiB requirement. A100-80GB was chosen instead for ~29.6 GiB
of margin and roughly twice the memory bandwidth.

Note what the crash did **not** indicate. FP8-Marlin on Ampere worked
(`Weight-only FP8 compression will be used leveraging the Marlin kernel`),
weights loaded from the Volume in 18.13 s with no re-download, and
`--reasoning-parser qwen3` was accepted. Only the KV allocation failed.

While Modal retried the crashing container it kept billing, so the app was
stopped with `modal app stop` to halt the loop. That is the failsafe described
in `design.md` being used for its intended purpose — an unexplained cost
source that could not be left running — not as a routine cost strategy.

**2026-09-24 — Gateway wired, and the free probe paid off.**
LiteLLM runs at `http://localhost:4000` with model `qwen3.8-27b`. Config lives
outside the shared `dev_config.yaml` so that `num_retries: 0` does not affect
other models on the same gateway.

Task 4.2a, the zero-cost probe, returned the decisive signature:

```
litellm.AuthenticationError: OpenAIException -
modal-http: invalid credentials for proxy authorization.
Received Model Group=qwen3.8-27b
```

`invalid` rather than `missing` means LiteLLM forwarded the bearer token and
Modal's edge rejected the value — so the credential path works end to end. No
container started and no GPU time was billed. The entire gateway-to-backend
question was settled before a single GPU-second was spent on it, which is the
property that made this probe worth designing.

Verified independently rather than accepted on report:

| Requirement | Evidence |
|---|---|
| Bearer token from env, not literal | `api_key: os.environ/MODAL_PROXY_TOKEN` in config |
| Timeout above cold start | `timeout: 900` and `stream_timeout: 900` vs 514 s measured |
| Retries bounded | `num_retries: 0` in both `router_settings` and `litellm_settings` |
| Three health-check suppressions | all present in config |
| Nothing polling | **0** references to the Modal endpoint in the live proxy log |

The zero-outbound-calls observation is supporting evidence, not proof. Task 4.8
still requires an overnight billing check, because only the invoice can confirm
suppression.

**End-to-end through the gateway (4.5, 4.6, 4.7).** Run against a container
still warm from the 5.4 measurements, which avoided an 8.5-minute cold start.

| Check | Result |
|---|---|
| 4.5 response via LiteLLM | `'\n\nI am working.'`, 54 completion tokens — **identical to the direct endpoint** |
| 4.5 latency (warm) | 2.58 s |
| 4.6 streaming | 55 SSE chunks, TTFT **0.50 s**, incremental deltas |
| 4.7 invalid gateway key | **401 in 29 ms**, never forwarded, no container started |

LiteLLM renames the model's `reasoning` field to **`reasoning_content`**, the
conventional name for OpenAI-compatible providers. Reasoning is preserved rather
than dropped: 47 `reasoning_content` chunks against 5 `content` chunks in the
streamed response. Clients that understand `reasoning_content` will render
thinking separately; those that do not will simply show the answer.

### 2026-09-24 — GPU memory snapshots: tried, measured, reverted

**Outcome: net negative for this model. Reverted.** Cost of finding out: ~$3.90.

The hypothesis was well-founded. vLLM reported that of a 319 s cold start,
`init engine (profile, create kv cache, warmup model) took 220.92 s` — 69% of
the total, and exactly what a snapshot skips. Compilation had already fallen to
1.44 s, so no further free improvement was coming.

Implementation required restructuring `deploy.py` from a function into a class
with `@modal.enter(snap=True/False)` hooks, vLLM sleep mode
(`--enable-sleep-mode`, `VLLM_SERVER_DEV_MODE=1`), a warmup request, and
`/sleep?level=1` plus `/wake_up` orchestration. Memory went 32 → 64 GiB because
level-1 sleep offloads 28.9 GiB of weights to CPU RAM; the dashboard later
showed 49.6 GiB actually in use, confirming 32 GiB would have failed.

Five measured cold starts with snapshots enabled:

| Run | Duration | What happened |
|---|---|---|
| 1 | 743 s | snapshot setup |
| 2 | 580 s | snapshot setup |
| 3 | **41 s** | genuine restore — weights + KV cache woke in 3.58 s |
| 4 | 784 s | re-created the snapshot instead of restoring |
| 5 | 522 s | slow again |

Median **580 s**, mean **534 s**, against a **319 s** baseline without
snapshots. One restore in five worked; the rest paid the full setup cost, which
exceeds a plain cold start.

The decisive argument is variance rather than the average. A 784 s worst case is
**13 minutes**, against a predictable ~5 minutes before. For a pilot whose
purpose is partly to make a good impression, unpredictable 41 s-to-13 min is
worse than reliable 5 min.

Modal's published 10x figure comes from a **3B** model. At 28.9 GiB the snapshot
does not reliably stabilise — that appears to be a size effect, and it is a
result nobody has published.

A process note worth keeping: run 3's 41 s was reported here as promising before
runs 4 and 5 existed. One good measurement surrounded by bad ones is a
hypothesis, not a result, and it should not have been framed as anything more.
Equally, runs 1 and 2 were called a failure prematurely when Modal's
documentation had already said snapshots need up to five cold starts to become
effective. Both errors came from concluding before the evidence was in.

### 2026-09-24 — Post-revert verification (task 6.4)

| Check | Result |
|---|---|
| Cold start | **300 s** — below the 319 s baseline |
| Sanity request | 200 OK, 1.04 s, `"OK."` |
| 400-word test | 200 OK, 12.92 s, `finish_reason=stop` |
| Visible tokens | **578**, reasoning 0, **3,257 characters** |

Byte-for-byte the same output as before the snapshot experiment. The revert is
clean and the endpoint is fully working.

**A transient HTTP 500 appeared on the first attempt**, with
`modal-http: internal error: status InternalFailure: Server has lost track of
input`. That is a Modal platform error, not a vLLM one — vLLM logged
`GET /v1/models 200 OK` throughout. It did not reproduce.

The probable cause was the test harness rather than the deployment: the
readiness poll fired every 3 s for 447 s, queueing roughly 150 inputs against
`max_inputs=32`. Polling every 10 s with a 5 s settle after readiness produced
a clean run. Worth remembering when writing load tests against a scale-to-zero
backend — aggressive polling during a cold start is itself a load pattern.

**The compile cache recovered on its own.** Changing the image to add
`VLLM_SERVER_DEV_MODE` for the experiment, then removing it, partially
invalidated `torch.compile`:

| Run | Init engine | Compilation |
|---|---|---|
| Baseline, warm cache | 220.92 s | 1.44 s |
| First run after revert | 256.59 s | 16.60 s |
| Second run after revert | — | recovered, total 300 s |

A cost of the experiment worth anticipating next time: **changing the image to
test something invalidates the cache that made the baseline fast**, so the first
measurements after any image change are not comparable to earlier ones.

### 2026-09-27 — 250K context with a BF16 KV cache FITS (tasks 1.3, 1.4, 1.6)

**No OOM.** The failure mode that killed the A100-40GB did not recur at four
times the context length with double the KV bytes per token.

| Measurement | Value |
|---|---|
| Cold start, 250K + BF16 | **655 s** (~11 min) |
| Free GPU memory at startup | 78.84 / 79.25 GiB |
| Budget at 0.90 utilization | **71.33 GiB** |
| Weights resident | **29.34 GiB** |
| Available for KV cache | **~42 GiB** |
| `init engine` | **457.83 s** (compilation 99.32 s) |
| Graph capture | 54 s, 0.46 GiB |
| CUDA graph pool | 0.46 GiB actual vs 0.83 GiB estimated |
| KV cache group sizes | [784, 784, 784, 784] |

The ~42 GiB of KV headroom matches the ~43 GiB the design predicted, so the
per-token arithmetic was sound this time. What could not be predicted — whether
the minimum page allocation scales with `max-model-len` — turned out not to
bite.

**Cold start more than doubled**, 300 s → 655 s. Most of it is `init engine` at
457.83 s, and 99.32 s of that is compilation: changing `max-model-len` and the
KV dtype produces a new compilation target, so the `vllm_cache` Volume was cold
for this configuration. It should fall on subsequent starts, as it did in phase
one (602 → 514 → 428 → 300 s).

**Task 1.5 did not fire.** Its condition was an OOM at 250K; there was none, so
the fallback to 200K and then to an FP8 KV cache was not needed.

**Task 1.6 — prefix caching is already enabled by default.** The earlier log
showed `Prefix cache hit rate: 85` and `86`, which cannot be reported unless the
cache is active. So `--enable-prefix-caching` is **not** an available
improvement — adding it and attributing a gain to it would have been exactly the
false result the design warned about. vLLM's V1 engine also enables chunked
prefill by default.

### 2026-09-27 — Long context genuinely works (tasks 2.1, 2.2, 2.3)

A 142,609-token synthetic audit document was built with unique reference codes
placed at the very beginning and the very end, so that retrieval could be
verified rather than assumed. The model was asked to report both plus a name
mentioned only in the closing section.

```
  1. ZX-4471-KESTREL    (start of document)   CORRECT
  2. QP-9928-FALCON     (end of document)     CORRECT
  3. Mariam Fouad       (closing section)     CORRECT
```

`finish_reason: stop`, 131 reasoning tokens and 35 visible. Retrieval from both
ends of a 142K-token prompt confirms the context is real rather than silently
truncated — a model that dropped the middle or the tail would have failed the
second and third items.

| Measurement | Value |
|---|---|
| Prompt tokens accepted | **142,609** |
| First run, cold prefix cache | **81.4 s** |
| Second run, warm prefix cache | **8.7 s** |
| Over-length request (2.2) | clean `400`, 7.4 s |

**The 81 s → 8.7 s difference is prefix caching working.** The second request
reused the cached 142K-token prefix, so prefill was almost free. This is the
exact traffic shape the feature targets, and it is already on by default — which
is why enabling it was never an available improvement.

The over-length error names the arithmetic precisely: *"maximum context length
is 250000 tokens... 249901 input tokens... total of at least 250001"*. A clean
rejection rather than an out-of-memory crash.

### 2026-09-27 — Thinking is back on, by operator choice

`CHAT_TEMPLATE_KWARGS` was changed from `{"enable_thinking": false}` to
`{"reasoning_effort": "medium"}` outside this workflow. That is a deliberate
configuration choice, not a regression, but it has a consequence worth stating:

**With thinking enabled, `max_tokens` must cover reasoning *plus* the answer.**
The first long-context attempt used `max_tokens: 120`, and all 120 went to
reasoning — `content` came back `None` with `finish_reason: length`, even though
the reasoning text contained all three correct answers. Raising the budget to
1500 produced 131 reasoning and 35 visible tokens.

Any client integration must account for this. A caller that sets a small
`max_tokens` will receive empty responses that look like model failure but are
budget exhaustion. This is the same failure that `enable_thinking: false`
originally fixed, now reintroduced as a trade for reasoning quality.

### 2026-09-28 — Fresh decode baseline, no MTP (task 3.4 prerequisite)

Task 3.4 originally compared against phase one's 44.5 tok/s. That figure was
measured on a different configuration — 128K context, FP8 KV cache, thinking
off — and by different code that included time-to-first-token in the decode
window. Comparing speculative decoding against it would have changed several
variables at once.

A fresh baseline was measured on the current configuration with
`eval/decode_bench.py`, which both halves of the comparison share:

| | Value |
|---|---|
| Configuration | 250K context, BF16 KV, `reasoning_effort: medium`, **no MTP** |
| Cold start | **403 s** (was 655 s on the first start of this config) |
| Decode, 3 runs | **49.3 / 49.4 / 49.3 tok/s** |
| Spread | **0.1 tok/s** |
| TTFT | ~0.95 s |

**The stale baseline would have inflated any gain by ~11%.** 49.3 is faster than
44.5 for reasons unrelated to speculative decoding — partly configuration,
partly methodology — which is the argument for measuring both halves with
identical code.

The 0.1 tok/s spread is unusually tight, so a speculative-decoding effect well
under 1 tok/s would still be distinguishable from noise.

Cold start fell 655 → 403 s between the first and second starts of this
configuration, as the compile cache filled — the same pattern as phase one.

### 2026-09-28 — MTP speculative decoding: 2.29x decode, kept (tasks 3.2-3.5)

Same code, same prompt, same configuration apart from the one flag.

| | No MTP | MTP, depth 3 |
|---|---|---|
| Decode, 3 runs | 49.3 / 49.4 / 49.3 | 113.3 / 112.2 / 112.7 |
| **Mean** | **49.3 tok/s** | **112.7 tok/s** |
| Spread | 0.1 | 1.1 |
| Cold start | 403 s | 740 s |

**2.29x decode.** The 63 tok/s difference is roughly sixty times the larger
spread, so this is not noise.

Acceptance, read from vLLM's own `SpecDecoding metrics` lines rather than taken
from the published figure:

| Window | Accepted / drafted | Rate | Mean acceptance length |
|---|---|---|---|
| 1 | 773 / 1,062 | 0.73 | 3.18 |
| 2 | 662 / 978 | 0.68 | 3.03 |
| 3 | 651 / 963 | 0.68 | 3.03 |

Per-position acceptance at the first draft slot was 0.83-0.86. Overall
acceptance of **0.68-0.73 sits slightly below the published 0.771** for the FP8
checkpoint, but a mean acceptance length above 3 — out of a maximum of 4 —
is why the gain is so large.

**The trade: long-context prefill slows down.** vLLM logged on startup:

```
max_num_scheduled_tokens is set to 2048 based on the speculative decoding
settings. This may lead to suboptimal performance. Consider increasing
max_num_batched_tokens to accommodate the additional draft token slots,
or decrease num_speculative_tokens.
```

A 2,048-token scheduling cap chunks a 142K-token prompt into roughly 70 steps.
Measured on the same 142,609-token document with a cold prefix cache:

| | Total |
|---|---|
| No MTP | 81.4 s |
| MTP | **94.8 s** (~16% slower) |

Both runs retrieved all three planted markers, so MTP does not affect
correctness — as expected, since speculative decoding only accepts tokens the
base model would itself have produced.

This is one measurement per configuration, so the 16% is indicative, not precise.

**Why it is kept anyway.** Under `reasoning_effort: medium` nearly every request
is generation-heavy: a 300-word answer consumed ~3,100 tokens, 88% of them
reasoning. Decode dominates, so a 2.29x decode gain outweighs a ~16% penalty on
the *first* read of a long document. Repeat reads are unaffected, because the
prefix cache removes prefill almost entirely (81.4 s → 8.7 s observed earlier).

**Next tuning lever, deliberately not pulled here:** raise
`--max-num-batched-tokens` as vLLM suggests, to recover long-context prefill
speed. That is a fourth flag, outside this change's scope, and left for the
operator's own tuning.

**One unexplained outlier.** The first measured MTP run had a TTFT of **135.9 s**,
against 2.44 s for the warmup before it and ~0.9 s for the two runs after. Decode
in that run was normal at 113.3 tok/s. It did not recur, and its cause is
unknown. Worth watching during real use: a user who hit it would see a
two-minute wait on a warm container.

### 2026-09-28 — `reasoning_effort: medium` empties generative answers at 1,200 tokens

In every baseline run, **all 1,200 completion tokens were reasoning; zero were
visible.** The prompt asked for a 300-word explanation. The model spent the
entire budget thinking and never began writing.

This does not affect the throughput measurement — decode speed is the same
whichever field a token lands in — but it matters for anyone using the endpoint:

| Task shape | Observed under `medium` |
|---|---|
| Extraction ("report these three codes") | 131 reasoning + 35 visible — fine at 1,500 |
| Generation ("write 300 words") | **1,200 reasoning + 0 visible** — empty at 1,200 |

Generative requests need either a much larger `max_tokens`, a lower effort
setting (`low`), or thinking disabled. A client sending a typical `max_tokens` of
1,000-2,000 for a writing task will receive empty responses that look like model
failure. The Copilot entry's 8,192 output limit probably clears it; LiteLLM
defaults and ad-hoc API callers may not.

### 2026-09-28 — `reasoning_effort: low` is now the default; answers are back

Redeployed with `CHAT_TEMPLATE_KWARGS = '{"reasoning_effort": "low"}'` (MTP
still on; cold start 664 s) and sent the exact request that came back empty:

| Effort | max_tokens | Reasoning | Visible | Words | finish |
|---|---|---|---|---|---|
| medium | 1,200 | 1,200 | 0 | 0 | `length` |
| medium | ~3,500 | 2,767 | 360 | ~300 | `stop` |
| **low** | **1,200** | **66** | **411** | **312** | **`stop`** |
| **low** | **2,000** | **66** | **411** | **312** | **`stop`** |

The two `low` runs are identical (temperature 0), so the budget no longer
binds: the model finishes with room to spare. For a comparable answer it used
477 tokens instead of 3,127 — about 6.5x fewer, which at the measured MTP rate
of ~113 tok/s is roughly 4 s of generation instead of ~28 s.

**What this does not show.** 66 tokens is barely any thinking. That is fine for
a writing task and says nothing about hard coding or long-document questions,
where the reasoning is the point. The evaluation therefore runs every task at
the default (what users actually get), and re-runs any task that fails at
`medium` via the per-request override, recording both. If `medium` fixes
failures that `low` produces, the default is costing quality and that belongs in
the findings.

### 2026-09-28 — The evaluation set is synthetic, by operator choice

Group 4 asked for tasks drawn from real company work. The operator chose instead
to have the set generated: 24 tasks (6 per area) about a fictional distribution
company, produced deterministically by `eval/make_data.py`.

What this buys: **every answer is known exactly.** Six tasks are graded by running
code (`eval/checks/`), and the rest against planted facts. Each check was first
run against a correct reference answer (must PASS) and a plausible wrong one
(must FAIL). All six discriminated, e.g. the SQL check caught `COUNT(*)` inflating
order counts roughly threefold, and the SKU check caught `\d` accepting Arabic-Indic
digits.

What it costs: the verdict is about capability on *this kind* of work. It is not
evidence about the company's own documents, formats or writing standards.

The long documents were sized with the model's own tokenizer, not a
characters-per-token guess. That matters most for the 195,259-token manual,
which has to stay under the 250,000 limit together with its answer budget:

| Document | Tokens | What it tests |
|---|---|---|
| Supply agreement | 75,099 | amendment overriding a clause; body vs schedule conflict |
| Shipment register | 136,649 | counting across ~700 lines; exhaustive listing to the last line |
| Operations manual | 195,259 | three-hop reasoning, facts at 0.2%, 76% and 100% |

Two generator bugs were caught by looking at the output rather than trusting the
code. Clause cross-references were off by one, because the body starts at
clause 2. A handwritten remark on the delivery note covered two printed
quantities, which would have made that vision task ungradeable. Both were fixed
before any model run.

### 2026-09-28 — Evaluation run: 18/24 at `low`, 20/24 at `medium`, no outright failures

Full write-up in `eval/FINDINGS.md`. The measured facts worth having here:

- **One warm window for everything.** A 313 s cold start (the fastest so far), both passes, and all repeats rode the same container, because the 10-minute idle window never expired between steps. Only one cold start was paid.
- **Long context works in practice.** 12/12 long-document answers were correct once the budget allowed, including 3-hop reasoning at 195K tokens and exact counting across 137K.
- **Long context is slow to generate.** Decode fell from ~125 tok/s on short prompts to 29 tok/s at 137K and 21 tok/s at 195K. Cold first read: 33 / 71 / 118 s at 75K / 137K / 195K. Cached follow-ups: ~3 s.
- **Changing `reasoning_effort` invalidates the prefix cache.** The kwarg changes the start of the prompt template, so the `medium` pass paid full prefill again.
- **`low` is not a cap on thinking.** One counting task used 5,928 reasoning tokens at `low` and was truncated at 6,000.
- **`medium` cost +21% time and +43% reasoning tokens** across the set, far below the 88% reasoning share measured on one writing prompt earlier.
- **Deterministic at temperature 0.** All 10 re-run shortfalls were byte-identical.
- **Vision prose uses U+2011 non-breaking hyphens in codes** (`LD‑1013`). They look right and do not match in lookups. JSON output was clean.

The idle window has been 10 minutes since a27b967 (2026-09-27), not 5. The
comment in `deploy.py` and the README still said 5, and both are now corrected.
Recorded here because earlier cost reasoning in this log assumed 5.

### 2026-09-28 — Gateway parity is exact, and the balance after evaluation is $8.66

Four evaluation tasks through LiteLLM came back byte-identical to the direct
runs. Determinism turns "looks the same" into an exact test. Tool calling
through the gateway returned the right call with the right arguments.

Balance $8.66 after the evaluation run: **$7.49 spent this phase against the
$12 ceiling**, within a cent of the estimate. The LiteLLM check reused the
still-warm container, so it cost its idle tail (~$0.50) and no cold start.

### 2026-09-29 — Run-to-run noise at 8 concurrent (task 4.2)

`interactive-8` and `interactive-8-repeat`, same config, back to back:

| | run 1 | run 2 | difference |
|---|---|---|---|
| visible p50 / p95 | 13.3 / 23.6 s | 12.6 / 23.5 s | 0.7 / 0.1 s |
| generation p50 | 75.3 tok/s | 72.5 tok/s | 2.8 tok/s (~4%) |
| total p95 | 28.3 s | 30.2 s | 1.9 s |
| throughput | 392 tok/s | 435 tok/s | 43 tok/s (~10%) |

A later "A beats B" claim at this level must exceed these. Throughput is the
noisiest figure, because the measured window is short and bursty.

One `interactive-8` request produced **no visible answer**: it thought for all
4,000 tokens (10,637 characters of reasoning) and was cut off. The repeat had
none. Counted as a failure, as the spec requires. It is the same
thinking-exhausts-the-budget failure seen in phase 2, and it happens
occasionally even at `low`.

### 2026-09-29 — FP8 KV cache: accuracy holds, capacity doubles, speed shifts (tasks 3.2-3.4)

**Startup (3.2).** Cold start 653 s: the first start of a new configuration,
as with every earlier config change. vLLM's KV-cache group size went from
**800 tokens per block on BF16 to 1,600 on FP8** at the same memory use
(29.86 GiB consumed, 0.9 utilisation). Each block now holds twice the tokens,
so KV capacity has doubled, which also confirms FP8 is active. The
`GPU KV cache size` line fell outside the log tail captured, in both phases.

**FP8 long-document re-check (3.3): 6/6 pass. FP8 kept.** Graded against the
same criteria as phase 2's BF16 results (`eval/results/2026-09-29/*@fp8.md`
vs `2026-09-28/*.md`, both at `low`):

| Task | BF16 (phase 2) | FP8 |
|---|---|---|
| longdoc-q3-late | Partial (cut off at 6,000 tokens; top answer right) | **Pass**: all 10 supplier counts exact, finished in 5,496 tokens |
| longdoc-rejections | Pass | Pass: 4/4 |
| longdoc-termination | Pass | Pass: 60 days, Amendment No. 2 |
| longdoc-payment-conflict | Pass | Pass: 8.2 vs D.4, clause 1.4 cited |
| longdoc-audit-manager | Pass | Pass: W6, Nadia Soliman, 15 April |
| longdoc-all-audit-failures | Pass | Pass: 5/5 |

The community benchmark's FP8 accuracy loss at 256K did not show up on these tasks.

**FP8 changes speed in both directions** (one request at a time):

| | BF16 | FP8 | |
|---|---|---|---|
| Short prompt, decode (decode_bench) | 112.7 tok/s | **73.2 tok/s** | -35% |
| 137K context, decode (q3-late) | 29 tok/s | **98 tok/s** | x3.4 |
| First read 75K / 137K / 195K | 32.9 / 70.8 / 118 s | 37.0 / 85.4 / 139.7 s | +12-21% |

The A100 has no native FP8 arithmetic, so every attention step converts
FP8 values back before use. That plausibly explains the slower short-prompt
decode and prefill, but it is not established. The x3.4 long-context decode
gain is larger than halving KV bytes alone would explain; its cause is
unknown. Under load, the doubled KV room matters more than single-request
speed, and the load test measures that directly.

**Method validation (3.4): generation speed agrees within 0.5%** (GuideLLM
72.8 vs decode_bench 73.2 tok/s, same prompt, same container). **TTFT
differs by ~0.45 s** (0.6 vs 1.07 s), which is more than the 10% bound. The
cause was found and measured: decode_bench opens a new TLS connection per
request, and `curl` shows TLS setup alone costs 0.34-0.36 s to this endpoint.
GuideLLM reuses its connection. A constant ~0.4 s offset in the client, not
the server, is immaterial against a 20 s target. GuideLLM's figure is the
closer one to server-side TTFT, and it is used.

### 2026-09-29 — The overnight polling check passes: LiteLLM ran 21 hours, zero GPU calls

This has been open since phase 1: does LiteLLM, left running unattended, wake the
GPU with health checks? LiteLLM ran continuously from 12:55 on 2026-09-28
(process start time) through the next morning. The Modal dashboard shows
no function calls between 15:00:40 on the 28th and 09:51 on the 29th, and the
balance did not move. **Closed.** Background health checks are off by default in
this gateway, which stores its models in its database rather than a config file.

The LiteLLM check at the end of phase 2 cost ~$0.81, not the ~$0.50 estimated:
$8.66 was read while the container was still in its idle window, and the
10-minute idle tail after the check followed.

### 2026-09-28 — Idle for ~19 hours at zero cost

The Modal dashboard showed the last function call at 17:59 on 27 September and
nothing further through to 13:00 the next day, with zero live containers. The
app remained deployed throughout.

This confirms scale-to-zero holds across a long idle period with the deployment
live. It is **not** a substitute for the phase-one overnight polling check:
LiteLLM was stopped during this window, so no gateway was present to poll. That
check still requires the gateway running unattended.

### 2026-09-27 — A flag value is not verified by appearing in a command

The first attempt at this configuration failed, and not for any interesting
reason: `--kv-cache-dtype bf16` is invalid. vLLM accepts `bfloat16`.

```
vllm serve: error: argument --kv-cache-dtype: invalid choice: 'bf16'
(choose from 'auto', 'bfloat16', 'float16', 'fp8', ...)
```

The container died during argument parsing and Modal retried it for ~25 minutes
before the test timed out. The verification that had been performed — confirming
the constant appeared in the built command — was satisfied by a wrong value.

This is the third instance of the same class of error, alongside the GPU type
string and the CUDA image tag. All three are values that Modal or vLLM validate
only at runtime and that cannot be checked locally. The lesson is narrow and
worth stating plainly: **confirming a flag is present is not confirming it is
valid.** Where a value comes from documentation rather than from a local API,
the first deploy is the test, and its failure should be expected rather than
treated as a surprise.

## Open items

- [ ] Confirm CPU/memory really are billed additively (first invoice).
- [x] ~~Confirm the `nvidia/cuda:12.8.1-devel-ubuntu22.04` base image satisfies
      vLLM >= 0.17.0~~ — **confirmed 2026-09-24**, image built and the download
      task ran on it.
- [x] ~~Confirm Modal accepts the GPU string `"A100-40GB"`~~ — **confirmed
      2026-09-24**, the `serve` function registers as `A100-40GB GPU` in the
      Modal dashboard.
