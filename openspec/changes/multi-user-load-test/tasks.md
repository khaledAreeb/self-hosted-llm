# Tasks

## 1. Load-test tooling (free, no GPU)

> Everything here is tested against GuideLLM's built-in mock server, which imitates an OpenAI endpoint on the laptop. No GPU time is spent until group 3.

- [ ] 1.1 Create `bench/` with a git-ignored `bench/.venv`. Install GuideLLM 0.7.x there with CPU-only torch, and verify `guidellm run --help` lists the `openai_http` backend and the `concurrent` profile. Also verify `git status` shows no `.venv` files.
- [ ] 1.2 Write `bench/make_datasets.py`. It builds `bench/datasets/interactive.json` from the 12 coding and report prompts in `eval/tasks.md`, reusing the eval parser. Verify the file has exactly 12 entries, each prompt matches its source task text, and none contains `FORMAT EXAMPLE`.
- [ ] 1.3 Write `bench/run.sh`, which runs one named workload (`interactive`, `agent`) at one concurrency level.
  - It reads the proxy token from `.env` at run time and passes it to GuideLLM's backend.
  - It applies the warmup/cooldown, `max(20, 3×N)` completions and 4-minute cap from design.md.
  - It writes to `bench/results/<date>/<workload>-<N>.json`.
  - Verify: a run against the local mock server produces the output file, and the dummy key used for the test appears nowhere in it.
- [ ] 1.4 Write `bench/metrics_sampler.py`. It polls vLLM's `/metrics` every 5 s through the authenticated URL and writes timestamped CSV rows for requests running, requests waiting, KV-cache use and preemptions, finding metric names by pattern, not hard-coding them. Verify it parses a saved Prometheus-format text sample correctly and keeps running, logging the gap, when a metric is missing or a poll fails.
- [ ] 1.5 Write `bench/summarize.py`. For each level it reads GuideLLM's output plus the sampler CSV and prints:
  - p50/p95 time to first token, time to first visible token, per-request generation speed and total time;
  - aggregate throughput, failed-request count and completed count;
  - peak running, waiting and KV use, and any preemptions.

  It then applies the "usable" targets from design.md and flags any level with fewer than 20 completions. Verify it produces a correct table from the mock-server runs made in 1.3.
- [ ] 1.6 Write `bench/README.md`: install, build datasets, run a level, run the sampler alongside, summarize. Verify every command runs exactly as written against the mock server.

## 2. Multi-user configuration (free until a request arrives)

- [ ] 2.1 In `deploy.py`, make both changes, each with a comment giving its reason and pointing to the accuracy re-check (task 3.3). Verify the file parses and `modal deploy` succeeds without starting a container (`modal container list` stays empty).
  - Set `KV_CACHE_DTYPE = "fp8"`, rewriting the comment that explains the earlier BF16 choice.
  - Add `max_containers=1` to `serve()`, and update the `MAX_CONCURRENT_REQUESTS` comment, which currently warns that no limit exists.

## 3. Window 1: gate, accuracy re-check, validation

> Paid. The spec requires the balance to be read before this group. The ~$2.80 window only runs if it stays inside the $4 ceiling.

- [ ] 3.1 Ask the operator for the Modal dashboard balance, record it in `NOTES.md`'s spend table, and verify it leaves at least $2.80 inside the ceiling. If not, stop here.
- [ ] 3.2 Trigger the cold start with the fatal-error log checks used in phase 2 (every 90 s), and record the cold-start time. Verify the startup log reports an FP8 KV cache, and a KV-cache token capacity about twice phase 2's BF16 figure.
- [ ] 3.3 Re-run the six `longdoc-*` tasks at the default effort (`eval/run_eval.py --tag fp8`). Grade each against its `eval/tasks.md` criteria and the retained BF16 result (`longdoc-*.md` from 2026-09-28), and record the comparison task by task in `NOTES.md`.
  - If accuracy holds, keep FP8.
  - If any task falls below its BF16 result, make and record the explicit accuracy-versus-concurrency decision the spec requires before going on. A BF16 fallback means another cold start: re-check the ceiling first.
- [ ] 3.4 Validate the method. On the warm container, run GuideLLM one request at a time on the `decode_bench.py` prompt, then run `eval/decode_bench.py 3`. Verify TTFT and generation speed agree within 10%, and record both. If they don't, find the cause or switch to the fallback script described in design.md before group 4.
- [ ] 3.5 Take the first `/metrics` scrape with the sampler. Record the actual metric names in `bench/README.md`, and verify all four series (running, waiting, KV use, preemptions) are populated.

## 4. Window 1: load runs

> Same warm window as group 3. The sampler runs throughout every level.

- [ ] 4.1 Run the interactive workload at 1, 4, 8, 16 and 30 concurrent. Verify each level either reaches `max(20, 3×N)` completions or is flagged as short, and that every level's output and sampler CSV are saved.
- [ ] 4.2 Repeat the interactive level at 8 and record the difference between the two runs in `NOTES.md` as run-to-run noise. Later "faster/slower" claims must exceed it.
- [ ] 4.3 Run the agent workload at 1, 4 and 8 concurrent (16K-token shared prefix, 1K unique, 300 output). Verify results are saved and the sampler shows no preemptions. If it does show any, record them as the finding.
- [ ] 4.4 Run the interference case: interactive at 8, with one 137K-token document request (given a unique first line so it isn't served from cache) sent mid-run via `eval/run_eval.py`. Record the document request's TTFT and total time, and the interactive p95 figures during versus outside its read.
- [ ] 4.5 End the window with `modal app stop` then `modal deploy`. Verify that `modal container list` is empty and `modal app list` still shows the app deployed, without sending any request, since a request would start a container.
- [ ] 4.6 Scan everything under `bench/results/` for the proxy token (the secret half), and verify there are no matches before anything is committed.

## 5. Window 2: MTP off under load (gated)

- [ ] 5.1 Ask the operator for the balance, record it, and verify it leaves at least ~$0.70 inside the ceiling. If not, skip group 5 and record the reason, per the spec's ceiling scenario.
- [ ] 5.2 Deploy FP8 without `--speculative-config`, cold start, and run the interactive workload at 8 and 30 with the sampler. End with stop and deploy, and verify `modal container list` is empty.
- [ ] 5.3 Apply the rule from design.md: keep MTP only if it is at least as good as off, by more than the task 4.2 noise, at the level nearest measured capacity. Set `SPECULATIVE_CONFIG` to the winner and update its comment with the under-load result. Deploy the final configuration, and verify with `modal app list`, not by sending a request.

## 6. Findings

- [ ] 6.1 Write `bench/FINDINGS.md`.
  - **Capacity per workload** against the targets fixed in design.md, quoting the targets beside each figure.
  - **Every knee attributed** from the sampler counters: waiting, KV full or preempted, or compute-bound.
  - **Measured results** for noise, long-document interference, FP8 accuracy and MTP.

  Verify every number cites a file in `bench/results/`.
- [ ] 6.2 Add the user table: capacity turned into people at a 10% and a 20% busy fraction for interactive users, and at 100% for agent users, with a mixed-team example and no single unconditional user count. Verify each figure shows its assumption.
- [ ] 6.3 Record the final spend against the $4 ceiling from a dashboard reading, and add the measured facts to `NOTES.md` (cold start of the FP8 config, noise, knees, MTP result). Verify the spend table has a row for each gate.
- [ ] 6.4 Update the docs:
  - `README.md` operating notes: measured capacity, `max_containers=1`, and what users should expect at busy times.
  - `deploy.py` comments: they must match the final configuration.
  - `GUIDE.md`: add a Part 11, "How to load test it yourself", covering the method, the gates and how to read the counters.

  Verify the README commands and the GUIDE's example commands run as written against the mock server.

## 7. Final verification

- [ ] 7.1 Verify the final deployed configuration is exactly one of the configurations exercised during a window: FP8 with MTP (window 1) or FP8 without (window 2). That way it is verified end to end without paying for another cold start.
- [ ] 7.2 From a fresh shell, follow `bench/README.md` against the mock server end to end, and verify it produces results and a summary in the same form as the retained ones. This covers the re-runnability requirement.
