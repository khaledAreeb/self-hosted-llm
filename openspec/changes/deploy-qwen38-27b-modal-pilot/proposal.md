# Proposal

## Why

The company wants a general-purpose LLM that its teams can use without sending prompts to a third-party API — data residency is the reason to self-host, not cost. Before anyone approves a recurring monthly GPU bill, we need evidence that the model is good enough and a measured number for what it actually costs to run.

We have a $30 Modal budget. That is roughly 12 GPU-hours: enough to stand up a real endpoint, put it in front of a small team for two to three weeks, and produce a defensible cost-per-user figure. It is not enough to run production, and this change does not attempt to.

## What Changes

- Deploy `Qwen/Qwen3.8-27B-FP8` on Modal behind vLLM (>= 0.17.0), exposed as an OpenAI-compatible HTTP endpoint.
- Use the **official FP8 checkpoint** rather than quantizing the model ourselves. Qwen publishes a fine-grained block-128 FP8 build that is near-lossless, which removes the quantization step from scope entirely and avoids the Gated DeltaNet sensitivity traps that make custom INT4 builds of this architecture risky.
- Run on a single **A100-40GB**, with **L40S** as a fallback if the Ampere FP8-Marlin path misbehaves with this model's hybrid attention layers.
- Serve on demand with scale-to-zero (`scaledown_window` 300s). No fixed schedule.
- Protect the endpoint with Modal proxy auth (`requires_proxy_auth=True`) so that unauthenticated traffic is rejected at Modal's edge before any GPU container starts.
- Route all team access through the **existing LiteLLM gateway**, which issues per-user virtual keys, enforces rate limits, and injects the Modal auth headers upstream.
- Suppress LiteLLM's background health checks for this model. Left at defaults they poll every 300s, which holds the container permanently awake and would consume the entire budget in roughly 12 hours with zero user requests.
- Capture duty cycle, latency, cost, and quality evidence sufficient to decide whether to fund a production deployment.

## Capabilities

### New Capabilities

- `model-serving`: An on-demand, authenticated, OpenAI-compatible inference endpoint for Qwen3.8-27B-FP8 that scales to zero when idle and starts only for authorized requests.
- `gateway-integration`: Team access mediated by the existing LiteLLM proxy — per-user API keys, upstream auth header injection, and the timeout, retry, and health-check settings that keep a scale-to-zero backend affordable and usable.
- `cost-observability`: The deployment must make its own operating cost measurable — duty cycle, GPU-hours, token throughput, and per-user attribution — so the pilot produces a defensible production forecast rather than an impression.

### Modified Capabilities

None. This is the project's first capability set.

## Impact

**New code**: a single Modal application file defining the image, weight-cache volumes, a one-time model download function, and the vLLM server. Deliberately kept to one file with constants at the top, because the implementer is deploying a model for the first time and the code needs to be readable more than it needs to be general.

**Existing systems**: the company's LiteLLM proxy gains one model entry and one set of upstream credentials. No change to how users authenticate — they continue to use LiteLLM-issued keys.

**External dependencies**: Modal (compute, ~$30 credit), Hugging Face (model weights, ~28 GB), vLLM >= 0.17.0.

**Budget**: ~12 GPU-hours total at approximately $2.54/hr effective on A100-40GB, including Modal's separately-billed CPU and memory. Overrunning this ends the pilot, so budget protection is a first-class requirement rather than an operational nicety.

## Non-Goals

- **Custom quantization.** Not needed; the official FP8 checkpoint exists. Revisit AWQ INT4 only after the model has proven itself, as a cost optimization with its own A/B against a known baseline.
- **The 9x5 production schedule.** Running a warm replica 9 hours a day, 5 days a week would exhaust $30 in under two working days. That schedule is the eventual target, sized from what this pilot measures.
- **Non-English usage.** Scoped to English. Published quantization evaluations for this model cover English, code, and vision only, and the multilingual picture would require separate validation.
- **Chat UI.** Access is via API key through LiteLLM. No Open WebUI or equivalent in this change.
- **Production hardening.** No high availability, no failover, no SLA.
