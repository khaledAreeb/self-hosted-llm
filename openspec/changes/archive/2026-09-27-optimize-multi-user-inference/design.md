# Design

## Context

See `proposal.md` — Why. Requirements are in `specs/inference-performance`.

The deployment serves `Qwen/Qwen3.8-27B-FP8` on a single A100-80GB via vLLM 0.30, reached through LiteLLM. Current serving flags:

```
--max-model-len 131072      --kv-cache-dtype fp8
--gpu-memory-utilization 0.90
--reasoning-parser qwen3    --default-chat-template-kwargs '{"enable_thinking": false}'
--enable-auto-tool-choice   --tool-call-parser qwen3_xml
```

What has been measured so far, all from ad-hoc requests rather than a controlled test:

| Condition | Result |
|---|---|
| Single request | 44.5 tok/s |
| Two concurrent | ~83 tok/s aggregate (~41 each) |
| Under agent load | prompt 117-753 tok/s, generation **14-38 tok/s** |
| TTFT, warm | 1.56 s |

The agent-load row is the one that matters. Generation collapses while prompt throughput stays high, which is the signature of a server spending its time on prefill. Agents resend the whole conversation each turn, so the same tokens are processed repeatedly.

Roughly **$21** remains of the original $30, and the pilot still needs most of it.

## Goals / Non-Goals

**Goals:**

- Attribute the slowness to a specific cause with a repeatable test, rather than tuning by intuition.
- Reduce repeated prefill work and improve decode speed using configuration only.
- Leave behind a load test that can be re-run whenever configuration changes.

**Non-Goals:**

- Any change requiring more or different hardware.
- Making agent workloads fast in absolute terms. 63 requests will remain 63 requests.
- Changing the model, quantization, or context length.

## Decisions

### Measure before changing anything

Every existing number came from a one-off request. They are adequate for spotting a 10x problem and useless for detecting a 20% improvement.

The previous phase demonstrated both failure modes of measuring badly: GPU snapshots were called a failure after two runs and a success after one good run, and both conclusions were wrong. A repeatable test with a recorded baseline is the correction.

The test drives N concurrent requests of two shapes — short chat-style prompts, and long prompts sharing a common prefix — and reports aggregate tok/s, per-request tok/s and TTFT. Both shapes are necessary because they exercise opposite paths: short prompts are decode-bound, long shared-prefix prompts are prefill-bound and are the only pattern where prefix caching can help.

### Find out what is already enabled before enabling it

vLLM's V1 engine turns chunked prefill on by default, and the string "Prefix cache" already appears in this deployment's logs. It is entirely possible that part of the intended optimization is already in force.

This matters beyond tidiness. Adding `--enable-prefix-caching` when it is already on, measuring a difference caused by noise, and recording it as a win would be a false result — and it would then be trusted.

So the first action after the baseline is to read the running server's actual configuration from its startup output. Cheap, and it may remove work from the plan rather than adding it.

### Speculative decoding via the model's own MTP head

The checkpoint includes `mtp.safetensors`, a multi-token prediction head this deployment has never used. vLLM enables it with:

```
--speculative-config '{"method":"mtp","num_speculative_tokens":3}'
```

The mechanism: the MTP head proposes several tokens at once, and the main model verifies them in a single forward pass. Accepted tokens are effectively free, so decode speeds up by roughly the acceptance rate.

The published acceptance figure for the **FP8** checkpoint — the exact build in use — is **0.771**. That is high enough to expect a real gain, which is why this is worth the spend.

The failure mode is specific and must be watched: when acceptance is low, every rejected token is wasted compute and throughput drops *below* baseline. Acceptance rate is therefore recorded alongside throughput, not inferred from the published figure. A published number measured on someone else's hardware is a reason to try, not evidence of a result.

`num_speculative_tokens: 3` is the documented starting point. Tuning it further is deliberately out of scope — the budget does not support a parameter sweep.

### Prefix caching, if it is not already on

If caching proves inactive, `--enable-prefix-caching` addresses the measured problem most directly: agents resending a growing conversation means the same prefix is re-processed on every turn.

There is a known interaction worth recording. With chunked prefill enabled — which V1 does by default — only the first chunk of a long prompt benefits from prefix caching, so the gain is smaller than the mechanism suggests. This is a documented limitation, not a misconfiguration, and it means a modest measured improvement should not be read as the feature failing.

Prefix caching also consumes KV cache that would otherwise hold other users' conversations, so its effect on concurrency is measured rather than assumed.

### Batching parameters last, and only if indicated

`--max-num-seqs` and `--max-num-batched-tokens` control how many sequences and tokens the engine batches per step. vLLM's published example for multi-user serving of this model uses 16 and 16384.

These come last because the evidence does not currently point at them. Two concurrent requests already scale near-linearly, which is what healthy batching looks like. They will only be tuned if the load test shows aggregate throughput plateauing as concurrency rises — the actual signature of a batching limit.

### Change one variable at a time, revert what does not help

Each configuration is measured against the baseline independently. Anything that fails to beat it is reverted and the negative result recorded.

This is the discipline that correctly rejected GPU memory snapshots: five measurements, a median of 580 s against a 319 s baseline, reverted despite one attractive 41 s outlier. The same rule applies here, and the code comment recording that rejection is the model for how a negative result should be preserved.

### A spend ceiling of $6, decided in advance

Roughly $21 remains and the pilot needs most of it. The ceiling for this change is **$6** — about 2 GPU-hours.

Setting it in advance matters: the previous phase spent $3.90 on snapshot optimization partly because there was no stated point at which to stop. When the ceiling is reached, the best configuration measured so far is adopted and tuning ends.

Cold starts cost roughly five minutes of GPU time each, so measurements are batched into as few warm windows as possible. Configuration changes require a redeploy and therefore a fresh cold start, which is the dominant cost of this work and the reason the number of configurations tested is deliberately small.

## Risks / Trade-offs

**Speculative decoding reduces throughput → ** Acceptance rate is measured, not assumed. Reverted if throughput does not beat baseline.

**Prefix caching starves concurrency → ** Concurrency is measured with caching both on and off. If it trades single-user latency for multi-user capacity, the trade-off is recorded and decided explicitly rather than silently.

**Improvements are too small to distinguish from noise → ** The baseline is run twice to establish variance first. A change smaller than observed run-to-run variance is not a result. This is the error made when 41 s was reported as promising in the previous phase.

**The budget is consumed before the pilot → ** A $6 ceiling with a balance check before every run. The pilot matters more than this optimization; a faster endpoint nobody has evaluated is worth less than a measured cost forecast.

**Optimizing something that is not the bottleneck → ** The previous phase spent $3.90 shortening a 300 s cold start, then discovered GPU *scheduling* had taken 22 minutes — four times longer, and untouched by that work. Hence measuring the real distribution before choosing what to optimize.

## Migration Plan

Every change is a flag in `deploy.py`'s `vllm serve` command. Rollback is removing the flag and redeploying; redeploying is free, and the endpoint URL and API contract do not change.

One operational note carried from the previous phase: **`modal deploy` does not restart running containers.** A container already serving keeps the old flags until it scales down. Measurements must therefore run against a container started *after* the redeploy, or they will silently measure the previous configuration.

## Open Questions

- **Is prefix caching already enabled by default?** Resolved in the first task by reading the server's startup output. Cheap, and it determines whether that work exists at all.
- **What MTP acceptance rate does this hardware achieve?** The published 0.771 is for the FP8 checkpoint but not necessarily this GPU. Measured directly.
- **Does aggregate throughput plateau as concurrency rises?** Determines whether batching parameters are worth touching. Answered by the baseline run itself.
