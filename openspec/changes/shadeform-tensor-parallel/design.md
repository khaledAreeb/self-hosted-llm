# Design

## Context

Motivation is in `proposal.md` (Why); required behavior is in
`specs/multi-gpu-serving/spec.md`.

**The current state of `shadeform_deploy.py`** (phase 4, commit `fa15833`):
- `split_offers()` keeps only offers with `num_gpus == 1` and 80 GB or more of GPU memory.
- `vllm_flags()` returns the 15 arguments checked flag for flag against `deploy.py` at `68cff7e`.
- `startup_script()` runs the container with `--gpus all --shm-size 16g`, and checks the driver on the first GPU only.
- The plan and READY output name one GPU.

**Facts this design relies on, checked on 2026-10-04:**
- **Shadeform lists multi-GPU VMs** with the same fields as single ones: `num_gpus`, `vram_per_gpu_in_gb`, `nvlink`, `interconnect`, `os_options`, a price for the whole VM, and `availability`.
- **A usable pair exists today:** MassedCompute `A100_80Gx2`, $2.70/hr, `ubuntu22.04_cuda13.0_shade_os`, PCIe, no NVLink. No 2-GPU offer in the listing had NVLink.
- **vLLM splits the model with `--tensor-parallel-size N`.** Its Docker page says the container needs `--ipc=host` or `--shm-size`, "particularly for tensor parallel inference". vLLM's recipes document tensor parallelism for the Qwen3-Next family, the hybrid architecture this model shares; for this exact model, with MTP and FP8 KV cache, it has not been run.
- **`bench/run.sh` can target any URL** (`--target`, `BENCH_API_KEY`), so phase 3's concurrency test can be repeated against a VM.

## Goals / Non-Goals

**Goals:**
- **A run without the option is provably unchanged.** The same flag list, the same startup script, and the same offers. The existing tests are the guard.
- **Fail fast and cheaply** when a multi-GPU VM is wrong, because it costs twice as much per minute.
- **One paid run that answers the real question:** is a second GPU worth $1.32/hr more for this team?

**Non-Goals (design level):**
- **Choosing tensor parallelism automatically.** The operator decides per run.
- **Pipeline parallelism, or vLLM's data parallelism inside one VM.** Tensor parallelism is what splits one model's memory and compute; the others answer different questions.
- **A configurable shared-memory size or NCCL settings** before a real run shows they're needed.

## Decisions

### `--tensor-parallel N`: an explicit per-run option, default 1

- **Where:** `offers` and `up`.
- **Allowed values:** 1, 2, 4 or 8 (vLLM needs the split to divide the model's attention heads evenly; powers of two are the safe set). Only 2 is tested in this change.
- **Default:** 1, so every existing command means what it meant.

*Alternatives:*
- **`--gpus N`.** Rejected: `--gpu H100` already means the GPU *type*. Two options one letter apart, with different meanings, invite mistakes on a paid command.
- **Inferring N from the offer** (use however many GPUs the VM has). Rejected: the operator asked to choose, and a 4-GPU offer turning up in the list would silently change the cost and the setup.

### The single-GPU path stays identical, by construction

- **Flags:** `vllm_flags(n)` returns today's 15 arguments unchanged for `n == 1`. For `n > 1` it appends `--tensor-parallel-size n` at the **end**, so the shared part stays in the order checked against `deploy.py`.
- **Script:** the startup script for N=1 is the same text as today's.
- **Tests:** they assert both things directly:
  - the N=1 flag list equals the one recorded in phase 4 task 1.2;
  - the N=1 `docker run` arguments equal today's expected list, which the script test already holds.

*Alternative:* a separate code path for multi-GPU. Rejected: two copies of the vLLM settings would drift, which is exactly what phase 4's flag check was built to prevent.

### Offers: exactly N GPUs, and the same rules per GPU

- **Exactly N:** `num_gpus == N`, not "at least N". A 4-GPU VM for a 2-way split pays for GPUs it doesn't use.
- **Memory per GPU:** at least 80 GB, the same threshold as today, for every N. The 48 GB cards are out of scope (see the proposal).
- **CUDA:** the same rule as today; offers with older host drivers are listed as not usable, with the reason.
- **The listing for N>1** adds a **link** column from Shadeform's `nvlink`/`interconnect` fields. The N=1 listing keeps today's columns.

### The container for N>1: `--ipc=host` instead of `--shm-size 16g`

- **Why:** vLLM's documented choice for tensor parallelism. Shadeform's own Docker launch uses it by default, and the VM has no neighbors to share an IPC namespace with.
- **N=1:** keeps `--shm-size 16g`, which is measured and unchanged.

*Alternative:* a larger `--shm-size` (32 GB or more). Workable, but it means picking a number without data. `--ipc=host` removes the limit, as the docs suggest.

### Two GPU-count checks, cheapest first

1. **Right after create,** the tool reads `configuration.num_gpus` from `/info`. If it differs from N, the VM is deleted at once. This costs seconds instead of the 40-minute start limit.
2. **On the VM,** the startup script logs every GPU and `nvidia-smi topo -m`, and stops with `FATAL: N GPUs requested, M found` if there are fewer.
3. **vLLM itself refuses** to start a tensor-parallel group with fewer GPUs than requested. So READY implies all N GPUs are in use.

The weak spot: check 2 is only seen by the tool as "not ready", which means the 40-minute limit. Check 1 covers the realistic failure, Shadeform handing over a different machine. A VM that misreports its own GPUs is not expected.

### Reporting the link

- **Plan and READY output:** for N>1 they show `2 x A100 80 GB, tensor parallel 2, link: PCIe (no NVLink, per Shadeform)`.
- **The start log on the VM** holds `nvidia-smi topo -m`, the ground truth.

Every measured number is therefore recorded with the link that produced it.

### The paid measurement: one VM, compared with phase 3

On the 2x A100 VM, with `--hours 1` so the cost cap is $2.97:

| Measurement | Compared with (one A100, same settings) |
|---|---|
| `eval/decode_bench.py`: one person's writing speed | 77.5 tok/s (Shadeform, 2026-10-01) |
| `GPU KV cache size` in the vLLM log | 1,072,674 tokens (Shadeform, 2026-10-01) |
| Start time, by step | 15 minutes (phase 4) |
| `bench/run.sh interactive 8 --target <vm>`: 8 people at once | Modal A100, phase 3: p95 first word 23.6 s, missed the 20 s target |
| `code-sql-top-customers` check, and one tool call | pass |

The 8-person run decides it. Phase 3 found that one A100 misses the target
at 8 simultaneous requests. If two GPUs pass it, that's the case for them.

*Alternative:* also re-measure one A100 on Shadeform at 8 people at once, for a same-provider baseline. Not done: phase 4 showed the Shadeform A100 within 6% of Modal on single-stream speed with identical settings, so phase 3's numbers stand in, and a second VM would cost about $0.80 more. If the result is borderline, that's the follow-up.

## Risks / Trade-offs

- **[This model with MTP and the FP8 KV cache has never run split across GPUs]** → The first paid start is the test, and a failure deletes the VM (about $0.50–1). The tool stops; the logs are read over SSH (`--ssh-key-id`). A retry, for example with MTP off for N>1, is a code change with its own task and a **separate approval**, not an automatic second attempt.
- **[PCIe only, no NVLink: little or no speed gain]** → Measured and written down. Capacity (KV cache room) should still grow, because it depends on memory, not on the link.
- **[NCCL peer-to-peer can hang on some virtual machines]** → It would show as no READY, and the logs say why. The known workaround (`NCCL_P2P_DISABLE=1`) would be one more environment line for N>1, added only if the run shows the need, with approval to retry.
- **[A failed 2-GPU start costs twice as much per minute]** → The create-time GPU check catches a wrong VM in seconds. The 40-minute limit caps any other failure at about $1.80.
- **[The start may take longer than 15 minutes]** → It will be measured. If it nears the 40-minute limit, the limit is raised for N>1 only.
- **[The single-GPU path changes by accident]** → The tests compare it directly with phase 4's verified values. `deploy.py` (Modal) is not touched.
- **[No usable pair on the day]** → The tool says so and creates nothing. The test waits.

## Migration Plan

1. Add the option and the checks, with tests. Single-GPU tests must pass unchanged.
2. A live `offers --tensor-parallel 2` (free).
3. Docs, with the claims held back until measured.
4. One paid run, with the operator's approval.
5. Record the numbers, then decide whether to recommend it.

**Rollback:** without the option, the tool behaves exactly as in phase 4. To remove the option, revert this change's commits.

## Open Questions

- **Does `--ipc=host` alone make tensor parallelism work in this image on these VMs,** or does NCCL need more? The paid run answers this; the decision above stands either way.
- **Are vLLM's `/metrics` and `/health` reachable without the key?** As far as I know, `--api-key` protects only the `/v1` API. That would expose counters (never prompts) on both single- and multi-GPU VMs. It's worth checking with one `curl` during the paid run, and recording. It doesn't change this design.
