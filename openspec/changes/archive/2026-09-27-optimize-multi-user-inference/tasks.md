# Tasks

> **Spend ceiling: $6** (~2 GPU-hours) of the ~$21 remaining. Check the balance before each group. When the ceiling is reached, adopt the best configuration measured so far and stop tuning — the pilot needs the rest.

> **Cold starts cost ~5 minutes of GPU time.** Every configuration change requires a redeploy and therefore a fresh container. Batch measurements into as few warm windows as possible, and keep the number of configurations tested small.

> **`modal deploy` does not restart running containers.** A container already serving keeps the old flags until it scales down. Measure only against a container started *after* the redeploy, or you will measure the previous configuration and not know it.

## 1. Establish what is already true

- [ ] 1.1 Record the current Modal balance in `NOTES.md` as the starting point for this change's $6 ceiling, halting if under $8
- [ ] 1.2 Trigger one cold start and capture the full vLLM startup output to `bench/startup-baseline.log`, verifying the file contains the engine's resolved configuration rather than only progress bars
- [ ] 1.3 Determine from that log whether prefix caching and chunked prefill are already enabled, recording the finding in `NOTES.md` — if either is already on by default, note that enabling its flag is not an available improvement
- [ ] 1.4 Record the exact serving flags currently in force in `NOTES.md`, so later comparisons name the configuration they were measured against

## 2. Build the load test

- [ ] 2.1 Write `bench/loadtest.py` that issues N concurrent chat completions against the endpoint and reports aggregate tok/s, per-request tok/s and TTFT, verifying it runs against a warm container and prints all three figures
- [ ] 2.2 Give the test two prompt shapes — short chat-style, and long prompts sharing a common prefix — selectable by flag, verifying each produces measurably different prompt-throughput figures because they exercise prefill and decode differently
- [ ] 2.3 Make concurrency a parameter and confirm the test runs cleanly at 1, 4, 8 and 16 concurrent requests without errors or dropped responses
- [ ] 2.4 Have the test write results as JSON to `bench/results/<config-name>.json`, verifying two runs of the same configuration produce comparable files that can be diffed

## 3. Baseline, including its variance

- [ ] 3.1 Check the remaining balance and record it in `NOTES.md`
- [ ] 3.2 Run the load test at 1, 4, 8 and 16 concurrent with short prompts on the current configuration, saving results as `baseline-short`
- [ ] 3.3 Run the same sweep with long shared-prefix prompts, saving as `baseline-prefix`
- [ ] 3.4 **Re-run the 8-concurrent case a second time** and record the difference between the two runs in `NOTES.md` as the run-to-run variance — any later change smaller than this figure is not a result
- [ ] 3.5 Record in `NOTES.md` whether aggregate throughput plateaus as concurrency rises, verifying the conclusion against the measured curve — this decides whether group 6 is worth doing at all

## 4. Speculative decoding via the MTP head

- [ ] 4.1 Check the remaining balance and record it, skipping the rest of this group if under $3
- [ ] 4.2 Add `--speculative-config '{"method":"mtp","num_speculative_tokens":3}'` to the serve command as a named constant in `deploy.py`, verifying the file parses and the flag appears in the built command
- [ ] 4.3 Redeploy and confirm the server starts, verifying from the startup log that speculative decoding is active rather than silently ignored
- [ ] 4.4 Capture the observed acceptance rate from the server's own metrics or logs and record it in `NOTES.md` next to the published 0.771 figure for the FP8 checkpoint
- [ ] 4.5 Re-run the group 3 sweeps against a container started after the redeploy, saving as `mtp-short` and `mtp-prefix`
- [ ] 4.6 Compare against baseline and decide, recording the reasoning in `NOTES.md`: keep only if throughput beats baseline by more than the variance measured in 3.4
- [ ] 4.7 If it does not beat baseline, remove the flag and redeploy, verifying the endpoint returns a correct answer afterwards and recording the negative result so it is not retried without new evidence

## 5. Prefix caching, only if it is not already on

> Skip this group entirely if task 1.3 found prefix caching already enabled. Record the skip and its reason; do not enable a flag that is already in force and attribute a gain to it.

- [ ] 5.1 Check the remaining balance and record it, skipping the rest of this group if under $2
- [ ] 5.2 Add `--enable-prefix-caching` to the serve command, redeploy, and verify from the startup log that it is active
- [ ] 5.3 Re-run the long shared-prefix sweep against a fresh container, saving as `prefix-cache-on`, since this is the only traffic shape where the feature can help
- [ ] 5.4 Compare prompt throughput and TTFT against `baseline-prefix`, recording the result and noting that chunked prefill limits the benefit to the first chunk of each prompt — a modest gain is the expected outcome, not a failure
- [ ] 5.5 Check the effect on concurrency by re-running the short-prompt sweep, verifying whether cached prefixes have reduced the number of concurrent requests the GPU can serve
- [ ] 5.6 Decide and record: keep if it helps prefill without materially harming concurrency; if it trades one for the other, state explicitly which workload was prioritised and why

## 6. Batching parameters, only if the curve justifies it

> Skip this group unless task 3.5 found aggregate throughput plateauing as concurrency rises. Two concurrent requests already scale near-linearly, so there is currently no evidence that batching is the constraint.

- [ ] 6.1 Check the remaining balance and record it, skipping the rest of this group if under $2
- [ ] 6.2 Set `--max-num-seqs 16` and `--max-num-batched-tokens 16384` as named constants, redeploy, and verify the values appear in the startup log
- [ ] 6.3 Re-run the short-prompt sweep against a fresh container, saving as `batching-tuned`, and compare against baseline
- [ ] 6.4 Keep only if aggregate throughput at 8 and 16 concurrent improves by more than the 3.4 variance; otherwise revert and record the negative result

## 7. Adopt and document

- [ ] 7.1 Ensure `deploy.py` contains only the flags that measurement supported, verifying each remaining addition has a corresponding recorded result
- [ ] 7.2 Add a comment above each retained flag giving the measured gain and the configuration it was measured against, so a future reader knows why it is there
- [ ] 7.3 Record every rejected option in `deploy.py` with its numbers and an explicit "do not retry without new evidence", following the pattern used for the rejected GPU memory snapshots
- [ ] 7.4 Write `bench/README.md` covering how to re-run the load test and compare against a saved baseline, verifying the documented commands run as written
- [ ] 7.5 Update `NOTES.md` with a summary table of every configuration tested, its result, and the decision taken
- [ ] 7.6 Record total spend for this change against the $6 ceiling, verifying the figure from the Modal dashboard

## 8. Final verification

- [ ] 8.1 Confirm the endpoint still serves correctly on the adopted configuration: a real request through LiteLLM returns a coherent, non-empty answer with tool calling intact
- [ ] 8.2 Re-run the full baseline sweep on the final configuration and record the end-to-end improvement over the original baseline, stating plainly if the total gain was negligible
