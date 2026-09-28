# Design

## Context

See `proposal.md` — Why. Requirements are in `specs/capability-evaluation`.

Current serving configuration on a single A100-80GB:

```
--max-model-len 131072      --kv-cache-dtype fp8
--gpu-memory-utilization 0.90
--reasoning-parser qwen3    --default-chat-template-kwargs '{"enable_thinking": false}'
--enable-auto-tool-choice   --tool-call-parser qwen3_xml
```

Measured so far: 44.5 tok/s single request, ~83 tok/s across two concurrent, TTFT 1.56 s warm, cold start ~300 s. Roughly **$21** of the original $30 remains.

The model is a hybrid: of 64 layers only 16 carry a KV cache, the other 48 use Gated DeltaNet linear attention with a small constant state. That makes KV cache unusually cheap per token and is what makes a 250K context affordable at all.

## Goals / Non-Goals

**Goals:**

- Configure for fidelity at full context so capability can be judged fairly.
- Take the free speed win from the model's own MTP head.
- Produce a recorded, re-runnable picture of what the model does well and badly.

**Non-Goals:**

- Multi-user throughput. This configuration deliberately trades it away.
- Changing the model or the GPU.
- Tuning beyond the three named flags — the operator intends to continue personally.

## Decisions

### 250,000 tokens, deliberately just inside the native limit

Native context is 262,144. Going beyond it requires YaRN rope scaling, which alters the model's behaviour and would confound a capability evaluation: a weakness could be the model, or could be the scaling.

250,000 leaves headroom under that ceiling while being, for practical purposes, "full context".

```
  KV per token   16 attn layers x 4 kv heads x 256 head_dim x 2 (K,V)
                 = 32 KB/token at FP8,  64 KB/token at BF16

  250K @ BF16    15.26 GiB per full-length sequence
  KV pool        ~43 GiB     ->  ~2.8 concurrent at full length
```

Ample for solo evaluation.

### BF16 KV cache, accepting the concurrency cost

A community benchmark on this model measured KV precision at 256K native context: **BF16 scored 0.833, FP8 scored 0.717**. At 32K that gap does not appear; at 250K it is exactly the regime in question.

Evaluating long-document capability on an FP8 KV cache risks the worst kind of wrong conclusion — deciding the *model* is poor at long context when the *cache setting* was. Since the purpose here is judging the model, the setting that handicaps it least is the correct one.

The cost is real and must be stated rather than buried: concurrency at full length halves, from ~5.6 to ~2.8. That is the wrong trade for serving thirty people and the right one for one person judging quality. Whoever later optimises for throughput should revisit it, and the spec requires the reason to be recorded so they know it was a choice.

The sample size behind 0.833 versus 0.717 was small, so this is a reasonable precaution rather than a settled fact. Precaution is appropriate: the downside of being wrong here is a mistaken verdict on the model.

### Test memory before building anything on top of it

At 250K with BF16, one full sequence needs 15.26 GiB against a ~43 GiB pool. The arithmetic says it fits.

The arithmetic said the A100-40GB would fit, too. It died with CUDA out-of-memory because vLLM's *minimum* KV allocation is governed by page size rather than by per-token maths — the hybrid architecture forces a 1568-token attention block to match the Mamba page size, making even a minimal allocation 12.25 GiB.

Whether that minimum scales with `max-model-len` is unknown. If it does, 250K could exceed the pool.

So the first task after the configuration change is a cold start that either succeeds or does not, before any evaluation set is written against a deployment that may not run. A failed start costs about $0.30 and five minutes; discovering the problem after writing fifty evaluation tasks costs considerably more.

If it fails, the fallbacks in order are: reduce context to ~200K, then fall back to an FP8 KV cache, recording the trade.

### MTP speculative decoding, because it is free and orthogonal

The checkpoint ships `mtp.safetensors`, a multi-token prediction head the deployment has never used:

```
--speculative-config '{"method":"mtp","num_speculative_tokens":3}'
```

The head proposes several tokens at once and the main model verifies them in one forward pass, so accepted tokens are nearly free. Published acceptance for the FP8 checkpoint is **0.771**, high enough to expect a genuine gain.

It is included here rather than deferred because it neither trades against context nor against fidelity — it changes how tokens are produced, not what the model attends to. Speed makes evaluation less tedious, which matters when a long-document task takes minutes.

The failure mode is specific: when acceptance is low, rejected tokens are wasted compute and throughput falls *below* baseline. Acceptance is therefore observed rather than assumed, and the flag is removed if it does not help. A number measured on someone else's hardware is a reason to try, not evidence of a result.

### Check prefix caching rather than enabling it

"Prefix cache" already appears in this deployment's logs, and vLLM's V1 engine enables chunked prefill by default. Part of the intended optimisation may already be in force.

Adding `--enable-prefix-caching` when it is already on, then attributing an improvement to it, would produce a false result that is subsequently trusted. So the configuration is read from the running server's startup output first, and the flag added only if genuinely absent.

### An evaluation set that reflects the fleet's division of labour

The set covers four areas, chosen because each answers a distinct question:

| Area | Question it answers |
|---|---|
| Coding | Does it compete with the hosted models already in use? |
| Report writing | Can it produce work that goes to colleagues? |
| Long-document reasoning | Is the 250K context useful in practice, or only on paper? |
| Vision | Does the one capability no other model in the fleet has actually work? |

Vision and long context matter most. They are the two things this deployment offers that the existing OpenRouter models do not, so they are where its value has to come from if it has any.

Agentic coding is explicitly excluded from the set. That was already measured: two OpenCode sessions produced 63 requests and took 10-20 minutes, because agents multiply one question into dozens of sequential calls. Re-testing it would spend budget confirming a known answer.

### A $8 ceiling, set in advance

Roughly $21 remains. The ceiling for this change is **$8**, leaving room for the cost pilot afterwards.

Stating it in advance matters. The GPU snapshot experiment in the previous phase consumed $3.90 partly because no stopping point had been named, and it was reverted in the end. When the ceiling is reached, findings are written from whatever has been gathered.

Cold starts will be *longer* at 250K, since more KV cache is reserved at startup, and each configuration change forces a fresh one. Evaluation runs are therefore batched into as few warm windows as possible.

## Risks / Trade-offs

**OOM at 250K with BF16 → ** Tested first, before anything depends on it. Fallbacks: 200K context, then FP8 KV. This is the failure mode that already occurred once on this model.

**Speculative decoding slows things down → ** Acceptance rate observed; removed if throughput does not improve.

**Concurrency drops too far for other users → ** Accepted deliberately. This configuration is for evaluation. If others need the endpoint during it, they will notice, and that is itself information about the trade.

**Budget consumed before the cost pilot → ** $8 ceiling with a balance check before each group. The pilot matters more: a model judged excellent but never costed cannot be funded.

**Evaluation becomes a vibe check → ** Each task states what a good answer looks like before the model is run, and outputs are retained. Without that, "it seemed fine" is all that survives, and it convinces nobody.

## Migration Plan

Three flags in `deploy.py`. Rollback is restoring the previous values and redeploying; redeploying is free and the endpoint URL and API contract do not change.

Two operational notes carried forward:

**`modal deploy` does not restart running containers.** A container already serving keeps the old flags until it scales down. Evaluation must run against a container started *after* the redeploy, or it silently measures the previous configuration.

**`modal app stop` is an undeploy, not a restart.** It removes the endpoint entirely and returns 404 until redeployed. Use stop-then-deploy as a pair, or simply wait for the idle scaledown.

## Open Questions

- **Does the minimum KV allocation scale with `max-model-len`?** Unknown, and it determines whether 250K fits at all. Answered by the first task, cheaply.
- **What MTP acceptance rate does this hardware achieve?** The published 0.771 is for this checkpoint but not necessarily this GPU.
- **Is prefix caching already on?** Read from the startup output rather than assumed.
- **How much does BF16 KV actually help at 250K?** The 0.833-versus-0.717 figure comes from a small sample. Quantifying it properly is out of scope here, but the evaluation outputs would support a later comparison if it matters.
