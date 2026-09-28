# Tasks

> **Spend ceiling: $12** of the $16.15 remaining (verified 2026-09-27). Check the balance before each group. When the ceiling is reached, write findings from what has been gathered rather than continuing.
>
> The ceiling was raised from $8 after the real balance turned out lower than planned. The original $30 can no longer fund both this evaluation and the cost pilot (~$20.60), so this phase takes priority: if the model is not good enough, its cost does not matter, and quality evidence is what justifies asking for more budget.

> **Cold starts are longer at 250K** — more KV cache is reserved at startup. Every configuration change forces a fresh one, so batch evaluation into as few warm windows as possible.

> **`modal deploy` does not restart running containers.** A container already serving keeps the old flags until it scales down. Always evaluate against a container started *after* the redeploy.

> **`modal app stop` is an undeploy, not a restart.** It returns 404 until redeployed. Use stop-then-deploy as a pair, or just wait for the idle scaledown.

## 1. Prove the memory fits, before anything depends on it

- [x] 1.1 Record the current Modal balance in `NOTES.md` as the baseline for this change's $8 ceiling, halting if under $10
- [x] 1.2 Set `MAX_MODEL_LEN = 250_000` and `KV_CACHE_DTYPE = "bfloat16"` as named constants in `deploy.py`, verifying the file parses and both values appear in the built serve command
- [x] 1.3 Redeploy and trigger one cold start, verifying the server reaches a serving state and does **not** fail with CUDA out-of-memory during KV cache allocation — this is the failure that killed the A100-40GB and the arithmetic alone cannot rule it out
- [x] 1.4 Capture the full startup log to `eval/startup-250k.log` and record in `NOTES.md` the reported KV cache size, the init-engine duration, and the total cold start time at this context length
- [x] 1.5 If 1.3 failed with OOM, reduce `MAX_MODEL_LEN` to 200_000 and retry; if it still fails, revert `KV_CACHE_DTYPE` to `"fp8"` — **condition did not fire.** 250K with BF16 allocated cleanly: 29.34 GiB weights against a 71.33 GiB budget, leaving ~42 GiB for KV cache. No fallback needed
- [x] 1.6 Confirm from the same startup log whether prefix caching and chunked prefill are already enabled, recording the finding — if already on, note that enabling the flag is not an available change and do not add it

## 2. Confirm the long context actually works

- [x] 2.1 Send a request with roughly 200,000 tokens of real document text and verify a coherent answer referencing content from both the beginning and the end, which a model that silently truncates would fail
- [x] 2.2 Send a request exceeding 250,000 tokens and verify a clear context-length error is returned rather than a crash or an out-of-memory failure
- [x] 2.3 Record time-to-first-token and total duration for the 200K request in `NOTES.md`, since prefill at this length dominates latency and sets expectations for long-document use

## 3. Speculative decoding

- [x] 3.1 Check the remaining balance and record it, skipping this group if under $6
- [x] 3.2 Add `--speculative-config '{"method":"mtp","num_speculative_tokens":3}'` as a named constant, redeploy, and verify from the startup log that speculative decoding is active rather than silently ignored
- [x] 3.3 Record the observed acceptance rate from the server's metrics alongside the published 0.771 figure for this checkpoint
- [x] 3.4 Measure tokens per second on a warm container and compare against the 44.5 tok/s recorded before this change, using a comparable prompt
- [x] 3.5 Keep it only if throughput improved; otherwise remove the flag, redeploy, and record the negative result so it is not retried without new evidence

## 4. Build the evaluation set

> Free — no GPU time. The tasks must come from real company work; generic prompts produce a verdict nobody will act on.

- [x] 4.1 Write `eval/tasks.md` with 20-40 concrete tasks across four areas — coding, report writing, long-document reasoning, vision — verifying each entry names a real task rather than a generic instruction
  - **Amended 2026-09-28, operator decision:** the tasks are synthetic rather than drawn from real company work. 24 concrete tasks (6 per area) set in a fictional distribution company, generated deterministically by `eval/make_data.py`. Every answer is known exactly, so grading is objective. The trade-off is that the findings describe capability on this *kind* of work, not value on the company's own documents.
- [x] 4.2 For each task, state what a good answer would look like **before** the model is run, verifying every entry has one — this is what separates evaluation from a vibe check
- [x] 4.3 Include at least three long-document tasks supplying real documents over 50,000 tokens, verifying they genuinely exercise context rather than merely being long-ish
  - Six tasks over three documents of 75,099, 136,649 and 195,259 tokens (counted with the model's own tokenizer). The questions need aggregation, exhaustive listing, amendment precedence and three-hop reasoning, with facts placed from 0.2% to 100% of the way in, not a single needle.
- [x] 4.4 Include at least three vision tasks using real images — scanned invoices, delivery notes, screenshots, photos of damaged goods — since this is the only model in the fleet that accepts images and the capability is completely untested
  - Six rendered images (synthetic under the 4.1 amendment): two scan-style invoices, one with a planted arithmetic error; a delivery note with a handwritten remark; an unlabelled bar chart; a terminal traceback; and a shipping label rotated 90°.
- [x] 4.5 Deliberately exclude agentic coding and record why: two OpenCode sessions already measured 63 requests over 10-20 minutes, so the answer is known and re-testing would spend budget confirming it

## 5. Run the evaluation

- [x] 5.1 Check the remaining balance and record it, halting if under $4
  - $11.20 on 2026-09-28 (Modal dashboard): $4.95 spent this phase, $7.05 left under the $12 ceiling.
- [x] 5.2 Run the full set against the deployment in as few warm windows as possible, saving every output under a dated `eval/results/<date>/` folder (the run date; planned as 2026-09-27) alongside the exact serving flags that produced them
- [x] 5.3 Record per-task latency and token counts, verifying the long-document and vision tasks are reported separately since their cost profiles differ sharply from short prompts
- [x] 5.4 Note any task where the model failed, refused, truncated, or produced an empty answer, verifying each is reproducible rather than a one-off
  - All 10 shortfalls were re-run at the setting that produced them and came back byte-identical (deterministic at temperature 0, one request at a time). Three failure types recurred at both efforts and are recorded as systematic. Concurrent-batch determinism was not tested.

## 6. Write the findings

- [x] 6.1 Write `eval/FINDINGS.md` summarising what the model does well and badly per area, verifying every claim cites a specific retained output rather than an impression
- [x] 6.2 State plainly whether the 250K context proved useful in practice or only on paper, since it is one of two reasons this deployment exists
- [x] 6.3 State plainly whether vision works well enough to rely on, since it is the other reason and no other model in the fleet offers it
- [x] 6.4 Compare against the hosted OpenRouter models already in use for any task where both could plausibly be used, verifying the comparison names which is better and why
  - **Skipped by operator decision, 2026-09-28:** no comparison with the OpenRouter models is wanted. The runner supports one (`EVAL_URL`/`EVAL_KEY`/`EVAL_MODEL`) if that changes.
- [x] 6.5 Record the final serving configuration with a comment above each flag explaining why it is set that way, especially the BF16 KV cache and its concurrency cost, so whoever later optimises for throughput knows it was a deliberate trade
  - Added the missing comments (`GPU_MEMORY_UTILIZATION`, `MAX_CONCURRENT_REQUESTS`, `VLLM_PORT`). Corrected the idle-window comment and README, which still said 5 minutes after the value became 10 in a27b967. Flagged that no `max_containers` limit exists, so a burst beyond 32 in-flight requests starts a second A100.
- [x] 6.6 Record total spend against the $12 ceiling, verified from the Modal dashboard
  - $8.66 after the evaluation run (Modal dashboard, 2026-09-28, read during the final idle window): **$7.49 spent this phase against the $12 ceiling**. The group-7 LiteLLM check comes on top, estimated at ~$0.50.

## 7. Final verification

- [x] 7.1 Verify the endpoint still serves correctly end to end through LiteLLM on the final configuration: a real request returns a coherent, non-empty answer with tool calling intact
  - Through local LiteLLM (`qwen3.8-27B`): 4 tasks (code, report, 75K document, image) byte-identical to the direct runs; tool call correct (`get_stock_level`, exact arguments, `finish_reason: tool_calls`); SQL answer passes its automated check.
- [x] 7.2 Confirm `eval/tasks.md` and the retained outputs together allow the same evaluation to be re-run and compared after a future model or configuration change
  - `eval/make_data.py` regenerates all 9 inputs byte-identically (sha256 checked). The model's outputs are deterministic at temperature 0. Results, including a copy of `deploy.py`, are retained in `eval/results/2026-09-28/`.
