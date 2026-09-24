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

## Open items

- [ ] Confirm CPU/memory really are billed additively (first invoice).
- [x] ~~Confirm the `nvidia/cuda:12.8.1-devel-ubuntu22.04` base image satisfies
      vLLM >= 0.17.0~~ — **confirmed 2026-09-24**, image built and the download
      task ran on it.
- [x] ~~Confirm Modal accepts the GPU string `"A100-40GB"`~~ — **confirmed
      2026-09-24**, the `serve` function registers as `A100-40GB GPU` in the
      Modal dashboard.
