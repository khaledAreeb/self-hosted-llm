# Proposal

## Why

The team will use the deployment for general-purpose work: chat, coding, reports,
documents, sometimes images, and possibly coding agents. Nobody yet knows how
many people it can serve at once. Every measurement so far sent **one request
at a time**. The only concurrency evidence is from phase 1: two simultaneous
requests scaled well (~83 tok/s combined), but two coding-agent sessions dragged
one request out to 13 minutes. Before the company is asked to fund a pilot, the
real capacity of one A100 must be measured, not guessed. It decides whether one
GPU is enough, and what a rollout costs.

The deployment is also still configured for single-person evaluation. The BF16
KV cache halves memory capacity, and there is no container limit, so a burst
above 32 in-flight requests would start a second A100 at full price.
Measuring capacity on a setup the team will not use would answer the wrong
question.

## What Changes

- **Switch the serving configuration to what multi-user use needs**:
  - FP8 KV cache, since phase 2 recommended it before multi-user serving.
  - `max_containers=1`, so load queues on one GPU instead of silently doubling cost.
- **Re-check long-document accuracy on FP8** with phase 2's six long-document tasks, compared against the retained BF16 results. The spec requires FP8 to be kept only if accuracy holds.
- **A load test built on GuideLLM**, an existing load-testing tool from the vLLM project, not new code from scratch. It first has to prove its numbers match the existing single-request benchmark.
- **Three workloads** reflecting general-purpose use:
  - **mixed interactive**: real chat, coding and report prompts, stepped from 1 to 32 simultaneous requests;
  - **coding-agent style**: large repeated context, short replies;
  - **long-document interference**: one 137K-token request landing among interactive users.
- **MTP compared on vs off under load.** Its 2.29× gain was measured for a single request and may shrink or reverse when the GPU is busy.
- **Server-side counters** (running, waiting, KV cache use, preemptions) recorded during every run, so any slowdown can be explained, not just observed.
- **Findings that translate concurrent requests into users**, under explicit assumptions about how often each kind of user is actually sending, and a stated latency target that defines "usable".

## Capabilities

### New Capabilities
- `multi-user-capacity`: the deployment's measured behaviour under concurrent load. That covers the configuration it is measured on, the workloads, the latency target that defines "usable", the resulting capacity, and a load test that can be re-run after any change.

### Modified Capabilities
- None. No main specs exist in this project; earlier phases were archived without syncing.

## Impact

- **`deploy.py`**:
  - `KV_CACHE_DTYPE` changes to `fp8`, with a comment recording the accuracy re-check.
  - `max_containers=1` is added to `serve()`.
  - MTP is toggled temporarily for the comparison, then set to whichever wins.
- **New `bench/` folder**: datasets built from the phase 2 eval prompts, the run commands, a `/metrics` recorder, results, `bench/FINDINGS.md`, a README, and `bench/GUIDE.md` (a step-by-step learning guide to the whole phase, added at the operator's request).
- **New local dependency**: GuideLLM, in its own git-ignored virtual environment. It pulls in torch and transformers (installed CPU-only), a large download that stays out of the project's own code.
- **Cost**: roughly $3–4 of GPU time (two to three cold starts plus about 40 minutes of load), under a **$4 ceiling** checked before each group. That leaves about $4 of the remaining ~$8.
- **Users of the endpoint**: during test windows the endpoint will be slow for anyone else. The config change to FP8 applies to everyone afterwards.
