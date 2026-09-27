# Proposal

## Why

The endpoint works, but nobody has established what the model is actually *good at*. Every test so far has been a smoke test — "reply with one short sentence", a 400-word explanation — chosen to prove the deployment functions, not to judge the model.

Before committing to a monthly bill, the question that matters is whether this model does the company's real work well: writing code, producing reports, reasoning over long documents, reading screenshots and scanned paperwork.

Answering that requires running it the way it was built to run. Context is currently capped at 131,072 tokens against a native 262,144, and the KV cache is set to FP8 — a throughput optimisation that a published benchmark measures as materially worse at long context (0.717 against BF16's 0.833 at 256K). Evaluating long-document capability in that configuration risks blaming the model for a setting.

This change configures the deployment for capability rather than throughput, applies the optimisations that cost nothing and do not trade against context, and evaluates the model across real use cases.

## What Changes

- **Raise context to 250,000 tokens**, just inside the 262,144 native limit so no YaRN rope scaling is needed.
- **Switch the KV cache to BF16.** At 250K this costs concurrency (~2.8 full-length sequences instead of ~5.6) and buys fidelity. For solo evaluation that trade is clearly right; it should be revisited before multi-user serving.
- **Enable multi-token-prediction speculative decoding** using the `mtp.safetensors` head the deployment has never used. Published acceptance for the FP8 checkpoint in use is 0.771, and the mechanism is orthogonal to context length.
- **Confirm prefix caching** is active — likely already on by default in vLLM's V1 engine — and enable it explicitly if not.
- **Build a use-case evaluation set** covering coding, report writing, long-document reasoning, and vision, and run the model against it.
- **Record what the model is good and bad at**, in enough detail to support a funding decision and to serve as a baseline for any future configuration change.

## Capabilities

### New Capabilities

- `capability-evaluation`: The deployment must be evaluated against representative company work at its full context, with results recorded reproducibly so that a later configuration or model change can be compared against them.

### Modified Capabilities

None. `model-serving` and `gateway-integration` exist only as archived delta specs, never synced to main specs, so there is no current version to modify. The API contract, authentication and scale-to-zero behaviour are unchanged by this work.

## Impact

**Configuration**: three flags in `deploy.py`'s `vllm serve` command — context length, KV cache dtype, speculative decoding. No architectural change.

**Memory risk, and it is the real one.** At 250K with a BF16 KV cache, a single full-length sequence needs **15.26 GiB**. The KV pool is roughly 43 GiB, so it fits — but the A100-40GB already died once on a KV allocation that the arithmetic said would fit, because vLLM's minimum page allocation behaved differently than predicted. That failure mode is live here and is tested first, before anything else is built.

**Budget**: roughly $21 remains of the original $30. Cold starts cost ~5 minutes of GPU time and will be *longer* at 250K, since more KV cache is reserved at startup. Evaluation runs are batched into warm windows.

**Supersedes** `optimize-multi-user-inference`, archived unstarted. Its premise — lower the context to gain concurrency — conflicted with this goal and was partly mistaken: vLLM allocates KV cache per actual token, so `max-model-len` caps a single request rather than multiplying total capacity.

## Non-Goals

- **Multi-user throughput optimisation.** Deliberately deferred. This configuration trades concurrency for fidelity, which is the wrong trade for serving many users and the right one for judging the model. Revisit after the evaluation, with evidence.
- **Changing the model.** The MoE alternative is a larger decision that this evaluation should inform rather than pre-empt.
- **The cost pilot.** Duty cycle, cost per user and the production forecast remain future work — and are better answered once it is known whether the model is worth serving at all.
- **Tuning beyond the three named flags.** The operator intends to tune further personally once the capability picture is clear.
