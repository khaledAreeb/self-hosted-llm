# Proposal

## Why

The deployment feels slow under real use. The instinctive diagnosis — "it does not handle many users" — is not what the measurements show.

Concurrency already scales well: one request sustains 44.5 tok/s, two sustain ~83 tok/s in aggregate. Two users cost almost the same as one.

What was actually slow was agent traffic. Two OpenCode sessions produced **63 requests**, and during them the server reported prompt throughput of 117-753 tok/s against generation throughput of only 14-38 tok/s. The GPU spent most of its time **re-reading prompts**, because agents resend the entire growing conversation on every turn.

So the bottleneck is prefill waste and decode speed, not concurrency. This change targets those two directly, using configuration on the existing single GPU. There is no budget for more hardware: roughly $21 of the original $30 remains, and the pilot still needs most of it.

## What Changes

- **Establish a repeatable throughput baseline** before changing anything. The existing numbers come from ad-hoc requests, not a controlled test, so improvements cannot presently be attributed to anything.
- **Confirm which optimizations are already active.** vLLM's V1 engine enables chunked prefill by default, and "Prefix cache" already appears in the server logs. Some of the intended work may already be done, and enabling flags that are already on would produce a false result.
- **Enable multi-token-prediction speculative decoding** via `--speculative-config '{"method":"mtp","num_speculative_tokens":3}'`. The model ships an `mtp.safetensors` head that the deployment has never used, and the published acceptance rate for the FP8 checkpoint — the exact build in use — is **0.771**.
- **Explicitly enable prefix caching** if it is not already on, so repeated conversation prefixes are not re-processed on every agent turn.
- **Tune batching** (`--max-num-seqs`, `--max-num-batched-tokens`) against measured concurrency rather than defaults.
- **Measure each change independently** and keep only what demonstrably helps.

## Capabilities

### New Capabilities

- `inference-performance`: The deployment's throughput and latency characteristics under concurrent load must be measurable, attributable to specific configuration, and verified rather than assumed.

### Modified Capabilities

None. `model-serving` and `gateway-integration` exist only as archived delta specs and were deliberately not synced to main specs, so there is no current version to modify. This change does not alter the externally observable behavior those specs describe — the API contract, authentication, and scale-to-zero semantics are unchanged.

## Impact

**Configuration only.** Flags in `deploy.py`'s `vllm serve` command. No architectural change, no GPU change, no gateway change.

**Budget**: roughly $21 remaining. Each measurement run needs a warm container, and cold starts are ~300 s. The plan therefore batches measurements into as few warm windows as possible, and sets a spend ceiling with an explicit stop rule.

**Risk of regression.** Speculative decoding can *reduce* throughput when the acceptance rate is low, and prefix caching consumes KV cache that would otherwise serve concurrency. Every change must be measured against the baseline and reverted if it does not help — the same discipline that correctly rejected GPU memory snapshots in the previous phase.

## Non-Goals

- **More GPUs, tensor parallelism, or a different GPU.** Out of budget. If measurement shows one GPU cannot meet the target, that becomes evidence for a funding request, not work in this change.
- **Fixing agent workloads generally.** Agents inherently issue many sequential requests. Optimization can reduce the per-request cost; it cannot make 63 requests behave like one.
- **Changing the model, quantization, or context length.**
- **The pilot itself.** Duty cycle, evaluation set, and the cost forecast remain future work.
