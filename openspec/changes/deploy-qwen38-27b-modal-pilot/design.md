# Design

## Context

See `proposal.md` — Why. Requirements are in `specs/model-serving`, `specs/gateway-integration`, and `specs/cost-observability`.

Three constraints shape every decision below:

**The budget is ~12 GPU-hours, not a monthly allowance.** At roughly $2.54/hr effective on A100-40GB, $30 buys about 11.8 hours of GPU time in total. Anything that holds a GPU awake without serving a user is not a minor inefficiency — it is a material fraction of the entire pilot.

**The implementer is deploying a model for the first time.** Readability outranks generality. A design that is clever but opaque fails even if it works, because it cannot be debugged under budget pressure.

**Qwen3.8-27B is not a conventional transformer.** It is a hybrid attention model: of its 64 layers, only 16 run full gated attention and the remaining 48 run Gated DeltaNet linear attention with a constant-size recurrent state. Two consequences matter here. KV cache is unusually cheap — roughly 64 KB/token at BF16 and ~32 KB/token with an FP8 KV cache, against ~131 KB/token for a conventional dense model of this depth — so concurrency and context are affordable. And the DeltaNet projections are unusually sensitive to quantization, because error there feeds a recurrent state and compounds along a sequence. That sensitivity is the reason quantization is out of scope.

## Goals / Non-Goals

**Goals:**

- One readable file that a first-time deployer can reason about end to end.
- Every dollar of GPU spend traceable to either a deliberate test or a real user request.
- A staged build where each stage is independently valuable and independently stoppable.
- Change one variable at a time, so that a disappointing result has one candidate explanation rather than several.

**Non-Goals:**

- Abstraction, configurability, or reuse. Constants at the top of one file. Configuration can be extracted later if the deployment survives the pilot.
- Cold start optimization in the initial build. It is a measured improvement in a later stage, not a starting assumption.
- Any attempt to hit production latency or availability targets.

## Decisions

### Use the publisher's official FP8 checkpoint; do not quantize

The original plan was to spend the budget quantizing the model. That work is already done and published: Qwen ships a fine-grained block-128 FP8 checkpoint whose quality is near-identical to BF16.

Alternatives considered:

| Format | Size | Requires | Cheapest suitable Modal GPU | Verdict |
|---|---|---|---|---|
| NVFP4 | ~11 GB | Blackwell | B200 at ~$6.25/hr | Smallest but only runs on the most expensive hardware |
| AWQ INT4 | ~21.5 GB | Ampere+ | A10 24GB (very tight) | Deferred — see below |
| **Official FP8** | **~28 GB** | **Ada/Hopper native, Ampere via Marlin** | **L40S / A100-40G** | **Chosen** |
| BF16 | ~56 GB | 80GB card | A100-80G at ~$2.50/hr | Wasteful for a pilot |

NVFP4 is the trap worth naming explicitly: it is the smallest and fastest format, and chasing it would push us onto Modal's priciest GPUs. Minimizing VRAM is not the objective; minimizing cost per useful hour is.

AWQ INT4 is genuinely attractive later — the best-documented community build measures 99.84% macro-average recovery against FP8 across five suites, at 21.5 GB instead of 28 GB. It is deferred for three reasons. First, it buys speed and memory but no additional GPU-hours, and hours are the binding constraint. Second, that build's own documentation warns that its INT8 recurrent-state quantization may accumulate error over long sequences, and that long-context testing was weak — a risk concentrated exactly in multi-turn conversations, which benchmarks do not exercise. Third and decisively, introducing it now adds a second variable to a pilot whose job is to answer whether the *model* is good enough.

### Run on A100-40GB, with L40S as the fallback

| GPU | Effective $/hr | Hours for $30 | Est. decode | KV headroom |
|---|---|---|---|---|
| A10 24GB | ~$1.55 | ~19.4 | ~20 tok/s | ~2 GB — too tight |
| L40S 48GB | ~$2.39 | ~12.5 | ~22 tok/s | ~18 GB |
| **A100-40GB** | **~$2.54** | **~11.8** | **~39 tok/s** | **~9 GB** |
| A100-80GB | ~$2.94 | ~10.2 | ~51 tok/s | ~48 GB |

A100-40GB costs 0.7 hours against the L40S and returns roughly 1.8x the decode speed, because decode is memory-bandwidth-bound and the A100's HBM2e (~1.55 TB/s) far exceeds the L40S's GDDR6 (~864 GB/s). For a pilot whose purpose is partly to impress, perceived speed is the product.

The A10 is rejected despite offering the most hours: it would require an INT4 build, leaves roughly 2 GB for KV cache, and still only matches the L40S on speed. A pilot that runs out of memory in front of the team costs more than the hours it saves.

The fallback exists because A100 is Ampere and has no native FP8 tensor cores. vLLM runs FP8 checkpoints there as weight-only W8A16 through FP8 Marlin: the 28 GB memory saving is preserved, which is what drives decode speed, but compute dequantizes to BF16. Block-wise FP8 support landed in Marlin well before the vLLM version this model requires, so this should work — but it has not been verified against this model's DeltaNet layers specifically. If anything misbehaves, L40S is the path vLLM's own published recipe verified, with native Ada FP8.

Effective hourly rates include Modal's separately-billed CPU and memory (~$0.44/hr at 4 cores and 32 GiB), which adds roughly 20% on top of the headline GPU price. This additivity is inferred from Modal's pricing page listing them as separate line items, and should be confirmed against the first real invoice.

### One file, `vllm serve` as a subprocess, download as a separate step

Three choices that compound into a readable deployment:

**Subprocess over library.** Running `vllm serve` as a subprocess and exposing its port yields a complete OpenAI-compatible API for free. Wrapping vLLM's Python `LLM` class instead would mean writing and debugging a web layer that already exists. Roughly five lines against a hundred, and it satisfies the OpenAI-compatible API requirement by construction.

**Download as a one-time step, not on first boot.** The platform's official example lets the serving path pull weights on demand. For this budget that is a trap: any cache miss re-pulls 28 GB and bills for the transfer. A separate download function run once writes weights to a persistent volume; the serving path only ever reads.

**Constants at the top, no indirection.** No config file, no CLI arguments, no environment plumbing beyond the credentials that must not be committed. Indirection can be added once the deployment is understood; it cannot be debugged before then.

A second volume caches compilation artifacts, so that repeated cold starts do not repeat compilation work.

### Volume storage is free at this scale and is not a cost lever

Modal bills Volume storage at $0.09/GiB/month with the first 1 TiB free. The weights volume (~28 GiB) and the compilation cache (~5 GiB) together consume roughly 3% of that allowance, so storage costs nothing.

Stating this explicitly removes a tempting false economy: deleting a volume between pilot sessions saves nothing and costs a 28 GiB re-download. Even retaining the BF16 original, the FP8 checkpoint, and a future AWQ build side by side (~105 GiB) stays inside the free tier. Volumes are treated as permanent.

It also settles the direction weights travel. Modal pulls from Hugging Face over a datacenter link in minutes; uploading the same 28 GiB from a local machine would take hours and arrive at an identical result. The deployment always fetches from Hugging Face, never from the operator's machine. Keeping a local copy on the operator's own disk is reasonable insurance against a future on-premise migration, but it sits outside the deployment path and is a prerequisite for nothing.

Note that the checkpoint in use is the publisher's, already public under Apache 2.0. There is no locally-produced artifact to preserve. That changes only if a future change quantizes the model — that output would be genuinely unique and would need its own home, such as a private repository on the company's own Hugging Face account.

### Reject unauthorized traffic at the platform edge

The platform's official vLLM example publishes an unauthenticated public URL. For a $30 budget that is a live hazard: anyone who discovers the URL can start an A100.

Proxy authentication at the platform edge is chosen over application-level API keys because it rejects requests *before* a container starts. Application-level auth — vLLM's own `--api-key` — would mean spinning up a GPU in order to issue a 401, letting junk traffic bill us. The cost of that choice is that the endpoint no longer speaks a standard bearer-token protocol, which is resolved by the gateway decision below.

### LiteLLM is the access layer

Team access via a chat UI was considered and rejected. The company already runs LiteLLM, which resolves the protocol mismatch the edge-auth decision created: users present standard bearer tokens, LiteLLM injects the platform's custom auth headers upstream.

```
  users --Bearer sk-user-key--> LiteLLM --platform auth headers--> endpoint
```

This also deletes a requirement from the build. LiteLLM already records per-request timestamps, token counts, and user attribution — which is precisely the per-user data `specs/cost-observability` requires. No instrumentation needs to be written into the deployment itself.

### Suppress gateway polling — the single largest budget risk

LiteLLM's background health check polls every configured model on a default 300-second interval. The intended idle window is also 300 seconds. The interaction is pathological:

```
  T+0:00  health check --> container wakes
  T+0:05  health check --> idle timer reset
  T+0:10  health check --> idle timer reset
          ... container never scales down

  24/7 GPU at $2.54/hr = ~$61/day
  $30 budget exhausted in ~12 hours, zero users served
```

Shortening the idle window does not rescue this. At a 60-second window with 300-second polling, each cycle still costs a cold start plus idle time — roughly 14 GPU-hours per day, exhausting the budget in under a day.

Suppression is therefore layered: disable background health checks globally, disable them for this model specifically, and exclude the model from on-demand health probes. Three settings rather than one, because a known open defect reports the internal health check still crawling configured models despite the per-model flag.

Critically, the design treats configuration as unverified. The acceptance condition in `specs/gateway-integration` is observed zero cost across an idle period, not the presence of the settings. Flags claim; the invoice confirms.

### A five-minute idle window, not the example's fifteen

The platform's example ships a 15-minute scaledown window, written for users who are not counting dollars. With six usage bursts a day that is 90 minutes of paid idle GPU daily — about $3.80/day, roughly a third of the total budget per day. Five minutes costs about $1.27/day for the same pattern.

Five minutes is a starting value, not a conclusion. The request-gap distribution recorded by the gateway will show whether it should move, which is why `specs/cost-observability` requires timestamps sufficient to recover the arrival pattern.

There is a floor set by human rhythm rather than by cost. If a user pauses ninety seconds to read an answer before replying, a one-minute window produces a cold start in the middle of their conversation. Two to three minutes is the practical minimum regardless of what the cost arithmetic alone would suggest.

### Manual stop/start is a failsafe, not a cost strategy

Stopping the deployment between uses was considered as a cost control. It saves nothing. Modal bills no compute for a deployed app with no running container, so a scaled-to-zero deployment already costs zero outside working hours. The cost that actually remains is idle GPU time *inside* the working day, in the gaps between usage bursts — and that is governed entirely by the idle window, which stopping the app does not touch.

Manual stop does have value as a hard off-switch: a guarantee that nothing can wake the GPU. But it must not be used during the pilot, because it would defeat the verification it appears to support.

```
  Stopping the app each night makes the overnight
  zero-cost check pass automatically, even when the
  gateway is still polling. The defect is concealed
  rather than found, and resurfaces on the first
  night someone forgets to stop it.
```

The deployment therefore stays up for the duration of the pilot, so that the overnight check measures something real. Manual stop is retained as the fallback control for the case where unexplained cost appears and its source cannot be traced.

### Build in stages

| Stage | Outcome | Cost |
|---|---|---|
| 1 | Endpoint answers an authenticated request | ~1 hr |
| 2 | Gateway wired, polling verified off | ~0.5 hr |
| 3 | Team pilot, evidence collected | ~7 hr |
| 4 | Cold start optimization (optional) | ~1 hr |

Stages 1 and 2 together already constitute a working pilot. Stage 3 produces the evidence. Stage 4 is an optimization that may prove unnecessary. Each boundary is a place to stop with something of value, which matters when the budget is fixed and the material is unfamiliar.

Platform GPU memory snapshots are deliberately held to Stage 4. They are an experimental feature reported to cut vLLM cold starts by up to an order of magnitude, and nobody has published figures for a 28 GB hybrid-attention model. Measuring the before-and-after is itself part of the pilot's evidence, which requires an unoptimized baseline to exist first.

### Bound the context length explicitly

Native context is 262,144 tokens. Left at the default, KV cache reservation would consume the GPU. An explicit bound near 32K leaves ample room on a 40 GB card — at roughly 32 KB/token with an FP8 KV cache, 9 GB of headroom holds far more concurrent context than a small pilot team will use — while turning a would-be out-of-memory crash into a clear context-length error.

## Risks / Trade-offs

**Gateway polling drains the budget overnight → ** Layered suppression, plus a verification step that reads actual billing after an idle period rather than trusting configuration. This is the first thing to check every morning of the pilot. If cost still appears and its source cannot be traced from container start logs, stopping the app between sessions is the fallback control — accepted as a workaround only after the measurement has been attempted, never in place of it.

**FP8-Marlin on Ampere misbehaves with the DeltaNet layers → ** Smoke-tested in Stage 1 at a cost of roughly $2.50 before any further commitment. L40S fallback is pre-selected, and switching is a one-constant change.

**Cold start is slow enough to sour the demo → ** Gateway timeouts are set above the worst observed cold start so requests succeed rather than error. If the delay proves unacceptable, Stage 4 addresses it. A slow first token is recoverable; a failed request during a normal start is not.

**Retry storms multiply containers → ** Retries bounded to at most one during the pilot. Retries are a production availability feature; against a scale-to-zero backend on a fixed budget they are a cost amplifier.

**Budget exhausted mid-pilot → ** Every stage is preceded by a balance check, and the 9x5 schedule is explicitly out of scope because it alone would consume the budget in under two working days.

**Measured cost per token looks alarming → ** This is likely, not merely possible. At low utilization the effective rate can exceed a hosted API's by two orders of magnitude, because idle GPU time is amortized across few tokens. The mitigation is framing, prepared in advance: `specs/cost-observability` requires the utilization level to be stated alongside the figure, and requires the comparison to name data residency as what the premium buys. The arithmetic is better done by us than by a CFO.

**Low measured utilization undermines the production case → ** The response is to raise utilization by routing more internal workloads through the same endpoint rather than to abandon self-hosting. Because everything already flows through the gateway, that is a configuration change.

**Quality regressions specific to long conversations → ** Not a risk for FP8, which is near-lossless. Recorded here because it constrains the *future* AWQ evaluation: the retained evaluation baseline required by `specs/cost-observability` must include multi-turn cases, or the recurrent-state accumulation risk will go unmeasured.

## Migration Plan

Greenfield; nothing to migrate. Deployment is a forward-only sequence of the four stages, each gated on a budget check.

Rollback at any stage is stopping the deployment — there is no persistent state to unwind beyond cached weights, which cost nothing to retain and would be expensive to re-download. Withdrawing team access is a gateway-side key revocation and does not touch the deployment.

## Open Questions

- **Actual cold start duration for a 28 GB model on this platform.** Unknown until measured in Stage 1. Does not change the approach: the gateway timeout is set generously and Stage 4 exists to improve it if needed.
- **Whether GPU memory snapshots are worth their complexity here.** Answerable only with a Stage 1 baseline to compare against. Stage 4 is optional by construction.
- **Whether A100-40GB capacity is consistently available.** The L40S fallback is already designed in, so scarcity changes a constant rather than the design.
- **The right long-term idle window.** Five minutes is a defensible starting value; the request-gap data collected in Stage 3 will answer it properly.
