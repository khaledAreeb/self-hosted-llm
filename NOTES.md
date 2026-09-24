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
| Cold start, with snapshots (6.3) | | |
| Warm TTFT (5.4) | | |
| Warm output tok/s (5.4) | | |
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

## Open items

- [ ] Confirm CPU/memory really are billed additively (first invoice).
- [x] ~~Confirm the `nvidia/cuda:12.8.1-devel-ubuntu22.04` base image satisfies
      vLLM >= 0.17.0~~ — **confirmed 2026-09-24**, image built and the download
      task ran on it.
- [x] ~~Confirm Modal accepts the GPU string `"A100-40GB"`~~ — **confirmed
      2026-09-24**, the `serve` function registers as `A100-40GB GPU` in the
      Modal dashboard.
