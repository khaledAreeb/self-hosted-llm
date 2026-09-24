# Tasks

> Implementation constraint carried from `design.md`: the deployment is **one readable Python file** with constants at the top. No config files, no CLI argument parsing, no abstraction layers. The implementer is deploying a model for the first time — favour clarity over generality in every choice.

> Budget constraint: ~12 GPU-hours total. Groups 3 onward each begin with a balance check.

## 1. Account prerequisites and budget baseline

- [ ] 1.1 Install the Modal CLI into the project venv and authenticate, verifying with `modal profile current` that it reports the intended workspace
- [ ] 1.2 Record the starting Modal credit balance from the billing dashboard into `NOTES.md`, verifying the figure matches the expected $30 starting point
- [ ] 1.3 Create a Modal proxy auth token pair at the proxy-auth-tokens settings page and store the ID and secret in a Modal Secret, verifying with `modal secret list` that the secret exists and that neither value appears in any file in the project directory
- [ ] 1.4 Confirm `Qwen/Qwen3.8-27B-FP8` is publicly downloadable without a gated-repo acceptance step, verifying by fetching the repo's config file metadata from Hugging Face without credentials

## 2. Model weight caching

- [ ] 2.1 Write `deploy.py` with constants at the top (model ID, GPU type, idle window, context bound) and a Modal image definition installing vLLM >= 0.17.0, verifying with `python -c "import ast; ast.parse(open('deploy.py').read())"` that the file parses
- [ ] 2.2 Add two Modal Volumes to `deploy.py` — one for Hugging Face weights, one for vLLM compilation artifacts — verifying with `modal volume list` that both exist after first use
- [ ] 2.3 Add a one-time `download()` function that fetches the FP8 checkpoint into the weights volume, keeping it separate from the serving path so cold starts never re-download, verifying the function is decorated to run standalone
- [ ] 2.4 Run the download once and verify with `modal volume ls` that roughly 28 GB of weight files are present in the volume
- [ ] 2.5 Record the download step's actual cost in `NOTES.md`, verifying it against the Modal billing dashboard rather than estimating

## 3. Serving endpoint

- [ ] 3.1 Check the remaining Modal balance before starting this group and record it in `NOTES.md`, halting if under $25
- [ ] 3.2 Add the serving class to `deploy.py` that launches `vllm serve` as a subprocess against the cached weights and exposes its port as a web server, using the subprocess rather than vLLM's Python `LLM` class so the OpenAI-compatible API comes for free
- [ ] 3.3 Set the serving configuration to A100-40GB, an explicit context bound near 32K, an FP8 KV cache, a 300-second idle window, and a startup allowance of at least 10 minutes, verifying each value is a named constant at the top of the file rather than inline
- [ ] 3.4 Enable Modal proxy auth on the web endpoint so unauthorized requests are rejected at the edge, verifying the deploy output marks the URL as protected
- [ ] 3.5 Deploy and smoke-test with an authenticated chat completion request, verifying a coherent English response comes back and confirming the Ampere FP8-Marlin path works with this model's DeltaNet layers
- [ ] 3.6 If 3.5 fails to load or produces incoherent output, switch the GPU constant to L40S and re-run the smoke test, verifying the vLLM published recipe path works and recording the reason for the switch in `NOTES.md`
- [ ] 3.7 Send an unauthenticated request to the endpoint URL and verify from the Modal dashboard that it was rejected with no container start and no GPU charge
- [ ] 3.8 Request a completion with streaming enabled and verify tokens arrive incrementally rather than as one final block
- [ ] 3.9 Request a completion exceeding the configured context bound and verify a clear context-length error is returned rather than an out-of-memory crash
- [ ] 3.10 Measure and record the unoptimized cold start duration in `NOTES.md` as the baseline for any later optimization, verifying by timing a request issued after the container has scaled to zero
- [ ] 3.11 Wait past the idle window with no requests and verify from the Modal dashboard that the container scaled to zero and GPU billing stopped
- [ ] 3.12 Write a short `README.md` covering how to download weights, deploy, and call the endpoint, verifying each documented command runs as written

## 4. Gateway integration

- [ ] 4.1 Check the remaining Modal balance and record it in `NOTES.md` before starting this group
- [ ] 4.2 Add the model to the LiteLLM config as an OpenAI-compatible provider pointing at the Modal endpoint, with the Modal auth headers supplied via `extra_headers` sourced from environment variables rather than literals in the config file
- [ ] 4.3 Disable LiteLLM background health checks globally, disable them for this model specifically, and exclude the model from on-demand health probes — all three settings, because one is known to be insufficient — verifying each appears in the config
- [ ] 4.4 Set the LiteLLM request timeout above the cold start duration measured in 3.10, and cap retries for this model at no more than one, verifying both against the recorded cold start figure
- [ ] 4.5 Call the model through LiteLLM with a gateway-issued key and verify the response matches what the direct endpoint returns
- [ ] 4.6 Request a streamed completion through LiteLLM and verify tokens arrive incrementally at the client
- [ ] 4.7 Issue a request with an invalid gateway key and verify LiteLLM rejects it without forwarding to the backend and without starting a container
- [ ] 4.8 **Leave the gateway running overnight with no user activity, then verify from the Modal billing dashboard that zero GPU cost accrued** — this confirms polling suppression empirically, which configuration inspection alone cannot do
- [ ] 4.9 If 4.8 shows any overnight cost, identify the polling source from Modal's container start logs and suppress it, repeating the overnight check until cost is zero before proceeding
- [ ] 4.9a If the polling source cannot be traced after 4.9, adopt `modal app stop` between sessions as the fallback control and record in `NOTES.md` that the overnight check was never passed, verifying the team is told the endpoint must be redeployed before use
- [ ] 4.9b Confirm the deployment stays up for the remainder of the pilot rather than being stopped nightly, verifying `NOTES.md` records why — stopping it would make the 4.8 check pass automatically and conceal a polling defect rather than detect it
- [ ] 4.10 Mint per-user virtual keys with rate limits set high enough for interactive work but low enough to bound a runaway client, verifying by exceeding the limit with a test key and observing rejection
- [ ] 4.11 Document the LiteLLM configuration and the reason health checks must stay disabled in `README.md`, verifying the warning is prominent enough that a future operator will not re-enable them

## 5. Pilot evidence collection

- [ ] 5.1 Check the remaining Modal balance and record it in `NOTES.md`, confirming at least 7 GPU-hours remain for the trial
- [ ] 5.2 Assemble a fixed evaluation set of 20-50 representative English tasks drawn from real company work, saved to `eval/tasks.md`, verifying each entry is a concrete task rather than a generic prompt
- [ ] 5.3 Run the evaluation set against the deployment and retain all outputs under `eval/baseline/`, verifying the run is reproducible and the outputs are complete
- [ ] 5.4 Measure warm-request time to first token and sustained output tokens per second, recording both in `NOTES.md` and verifying the figures come from timed requests rather than theoretical bandwidth calculations
- [ ] 5.5 Distribute per-user keys to the pilot team with brief usage instructions, verifying at least one user outside the implementer successfully completes a request
- [ ] 5.6 Run the team pilot across two to three working weeks, checking the Modal balance at the start of each day and recording it in `NOTES.md`
- [ ] 5.7 Export the LiteLLM request log for the pilot period, verifying it contains per-request user identity, timestamp, and input and output token counts
- [ ] 5.8 Compute the duty cycle as billed GPU-hours divided by elapsed working hours, verifying the GPU-hours figure comes from Modal billing rather than estimation
- [ ] 5.9 Analyse the request-gap distribution from the exported timestamps and determine whether a different idle window would reduce cost, recording the recommendation in `NOTES.md`
- [ ] 5.10 Compute effective cost per million output tokens as GPU-hours divided by tokens actually produced, and record it alongside the utilization level it was measured at

## 6. Cold start optimization

> Optional. Skip this group entirely if Stage 3 cold starts proved acceptable to users or if budget is short — the pilot is already complete without it.

- [ ] 6.1 Check the remaining Modal balance and skip this group if under 2 GPU-hours
- [ ] 6.2 Enable Modal memory snapshots and GPU snapshotting on the serving class, verifying the deploy succeeds and the endpoint still answers correctly
- [ ] 6.3 Measure the cold start duration with snapshots enabled and compare against the 3.10 baseline, recording both figures and the improvement factor in `NOTES.md`
- [ ] 6.4 If snapshots degrade reliability or produce incorrect output, revert to the unsnapshotted configuration and record the outcome, verifying the endpoint returns to correct behavior

## 7. Production forecast and handoff

- [ ] 7.1 Write `FORECAST.md` projecting monthly production cost from the measured duty cycle, showing both the scale-to-zero projection and the fixed 9x5 window figure, verifying every number traces to a recorded measurement
- [ ] 7.2 Add a comparison against hosted API pricing for a comparable model, stating data residency as what the premium buys, verifying the effective cost per token used is the measured one from 5.10 with its utilization level stated
- [ ] 7.3 Add a quality summary to `FORECAST.md` drawn from the 5.3 evaluation outputs, verifying claims reference specific retained outputs rather than general impressions
- [ ] 7.4 Add a recommendation section naming the production GPU, idle window, and expected monthly cost, citing measured tokens per second rather than theoretical figures
- [ ] 7.5 Note in `FORECAST.md` that AWQ INT4 remains an untested 25% memory saving for a future change, and that any such evaluation must re-run the `eval/baseline/` set including multi-turn cases to detect recurrent-state error accumulation

## 8. Integration verification

- [ ] 8.1 Verify the full chain end to end from a fresh scaled-to-zero state: a user with a gateway key sends a streamed request, receives a coherent response, and the container later scales back to zero
- [ ] 8.2 Verify total pilot spend against the starting balance recorded in 1.2 and confirm the project stayed within the $30 budget, recording the final figure in `NOTES.md`
