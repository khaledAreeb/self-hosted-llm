# Tasks

> Branch `phase-5-shadeform`. Groups 1–2 are free: code, tests against fakes, and the public offer list. Group 3 is paid and gated: the operator reports the Shadeform balance and approves before any VM is created. `deploy.py` is not touched: every group ends by checking `git diff --quiet ee16ce7 -- deploy.py`, where `ee16ce7` is phase 5's starting commit.

## 1. The option, the flags and the offers (free)

- [x] 1.1 Add `--tensor-parallel N` to `offers` and `up`: accepts 1, 2, 4 or 8, default 1, and any other value is refused before anything is created. Make the vLLM flag list depend on N: today's 15 arguments, unchanged, for N=1, with `--tensor-parallel-size N` appended at the end for N>1. Verify:
  - a test asserts that the N=1 list equals the list recorded in phase 4 task 1.2, argument for argument;
  - a test asserts that the N=2 list is that list plus `--tensor-parallel-size 2`;
  - `up --tensor-parallel 3` exits with an error and creates nothing (fake API).
- [x] 1.2 Save a fresh sample of the public `/instances/types` that includes multi-GPU types: the MassedCompute `A100_80Gx2` (CUDA 13), a CUDA 12 `A100_80Gx2` (Crusoe), a 48 GB pair (`A6000x2`), and a 4-GPU type. Add it beside the phase 4 sample, which stays as it is. Verify the file is valid JSON and the offers test loads it.
- [x] 1.3 Make the offer filter keep exactly N GPUs with at least 80 GB each, and the same CUDA rule as today. For N>1, add a **link** column (from Shadeform's `nvlink`/`interconnect`) to the `offers` listing; keep the N=1 listing's columns exactly as now. Verify in `tests/test_shadeform_offers.py`, with no network:
  - N=1 results are unchanged on the phase 4 sample;
  - N=2 on the new sample lists the CUDA 13 2x A100 as usable and the CUDA 12 pair as not usable (with the reason), and never shows the 48 GB pair or the 4-GPU VM;
  - `--gpu` and `--region` still combine with it.
- [x] 1.4 Run `offers --tensor-parallel 2` against the live public API (free) and record what it lists today. Verify that no 48 GB pair is shown, and that any CUDA 12 pair appears under "not usable".
  - **Result (2026-10-04):**
    - **usable:** MassedCompute `A100_80Gx2` (desmoines-usa-1, $2.70, CUDA 13.0) and Scaleway `H100x2` (paris-france-1, $6.60, CUDA 13.0), both "PCIe, no NVLink";
    - **not usable:** Crusoe `A100_80Gx2` ($4.00, "newest host CUDA is 12.2");
    - **not shown:** the 48 GB `A6000x2` pairs;
    - the one-GPU listing is unchanged.
- [x] 1.5 Document the option in the README's Shadeform section: what it does, that the default is unchanged, `offers --tensor-parallel 2`, and that the benefit is **not measured yet**. Verify every command in that section runs as written against the fakes.

## 2. Starting a multi-GPU VM (free)

- [x] 2.1 Make the startup script follow N. For N>1:
  - run the container with `--ipc=host` instead of `--shm-size 16g`;
  - log every GPU and `nvidia-smi topo -m`;
  - stop with `FATAL: N GPUs requested, M found` if the VM has fewer;
  - pass `--tensor-parallel-size N` to vLLM.

  For N=1 the script must be the same text as today's. Verify in `tests/test_shadeform_script.py`, with fake `nvidia-smi`:
  - N=2 with two fake GPUs gives the exact expected `docker run` arguments;
  - N=2 with one fake GPU stops with the FATAL line and no `docker run`;
  - N=1 produces today's script, unchanged;
  - both modes pass `bash -n`, for stages A and B.
- [x] 2.2 In `up`, right after the VM is created, compare `configuration.num_gpus` from `/info` with N. If they differ, delete the VM at once, confirm billing stopped, and say why. Verify against the fake API: a fake that reports one GPU for a 2-GPU request is deleted within seconds, and a correct one proceeds.
- [x] 2.3 Show the GPUs in the plan and READY output for N>1: count, model, memory each, "tensor parallel N", and the link from Shadeform (e.g. "PCIe, no NVLink"). Leave the N=1 output as it is. Verify with the lifecycle test:
  - the normal path for `up --tensor-parallel 2` reaches READY with those lines;
  - the auto-delete spend limit uses the whole VM's price (1 h × $2.70 × 1.1 = $2.97);
  - every existing single-GPU case still passes unchanged.
- [x] 2.4 Update the README `up` examples and the troubleshooting section: the GPU-count failure, and where `nvidia-smi topo` is logged. Verify the commands run against the fakes, the three test files pass, and `deploy.py` is unchanged.

## 3. The paid measurement (gated: balance reported, approval given)

> Before this group: the operator reports the Shadeform balance (recorded in `NOTES.md`) and approves this one VM. Ceiling for phase 5: $5 of Shadeform credit, unless the operator sets another. Any second attempt needs its own approval.

- [x] 3.1 Record the balance, and verify `offers --tensor-parallel 2 --gpu A100` shows a usable pair at that moment. If none is usable, stop: nothing is created.
  - **Result (2026-10-04 11:01 UTC):** the balance is about $39.43 (from the operator). One usable pair: MassedCompute `A100_80Gx2`, desmoines-usa-1, $2.70/hr, PCIe, no NVLink (Crusoe's is not usable: CUDA 12.2). The run was approved with a $5 ceiling.
- [x] 3.2 Run `up --hours 1 --tensor-parallel 2 --gpu A100 --ssh-key-id <operator's key>`. Record:
  - the time of each start step;
  - the `GPU KV cache size` line;
  - the `nvidia-smi topo -m` output;
  - the price.

  Verify that READY is reached, that a request without the key is refused, and (one `curl`) whether `/metrics` answers without the key, recording the result. **If the start fails:** read the logs over SSH, record the cause, and stop. A fix, such as MTP off for N>1 or `NCCL_P2P_DISABLE=1`, becomes a new task with its own approval.
  - **Result (2026-10-04): READY in 21m25s,** with no fix needed. VM `541c534b`, MassedCompute `A100_80Gx2`, desmoines-usa-1, $2.70/hr.
    - **Provider start:** ordered 11:03:52, active 11:13:50, 10 min (**not billed**: `cost_estimate` stayed $0).
    - **From active:** image pulled in 2m26s; model download and load 172 s, with **14.99 GiB per GPU** (29.38 on one GPU); engine start 254 s, including a 52 s compile. vLLM was up at 11:25:04, and READY came 11m27s after active (12m08s on one A100).
    - **GPUs:** 2x "NVIDIA A100 80GB PCIe", driver 580.126.09. `nvidia-smi topo -m` shows **PHB** (through the CPU's PCIe host bridge).
    - vLLM: *"Custom allreduce is disabled because your platform lacks GPU P2P capability"*, so it used **NCCL through host memory**. MTP works with the split.
    - **`GPU KV cache size: 2,933,139 tokens`**, 11.73x for 250K (one A100: 1,072,674, 4.29x).
    - **Key:** `/v1` without the key gave 401. **`/metrics` and `/health` answer without the key** (200; 426 `vllm:` counter lines, no prompts). This is the same on every VM, and is recorded for a later fix.
- [x] 3.3 On the same VM, measure against the single-A100 baselines in design.md:
  - `eval/decode_bench.py` (single-person speed; baseline 77.5 tok/s);
  - `eval/run_eval.py code-sql-top-customers`, which must pass;
  - one tool call;
  - `bench/run.sh interactive 8 --target <vm> --label tp2-interactive-8` (baseline: p95 first word 23.6 s on one A100).

  Verify each result is saved (`eval/results/<date>/`, `bench/results/<date>/`).
  - **Result (2026-10-04):**
    - **One person:** 82.9 tok/s (82.1–83.7), against 77.5 on one A100: **+7%**.
    - **Correctness:** `code-sql-top-customers@shadeform-tp2` **PASS**; the tool call returned `get_weather({"city": "Cairo"})` in 1.4 s.
    - **8 at once** (`bench/results/2026-10-04/tp2-interactive-8`, 25/25 measured, 0 failures): first visible word p50/p95 **20.8 / 35.0 s**, writing p50/p5 **48.9 / 43.2 tok/s**, throughput **307 tok/s**, peak KV use 5%.
    - **One A100 on the same workload** (phase 3, `2026-09-29/interactive-8` and `-repeat`): 13.3 / 23.6 s, 75.3 / 66.3 tok/s, 392–435 tok/s.
    - **Verdict: worse under load,** about 35% slower writing. It also misses the 20 s target. MTP mean acceptance length under load was 3.50–3.53.
    - The 8-at-once run used `BENCH_API_KEY` and `METRICS_URL` set to the VM, with `MODAL_PROXY_TOKEN` set to the VM key, so `.env`'s Modal token was never loaded or sent to the VM.
- [x] 3.4 Run `down` and verify that `status` shows nothing and Shadeform lists the VM as deleted. Record the spend from Shadeform's `cost_estimate` against the ceiling.
  - **Result (2026-10-04):** `down` at 11:29:21. `deleting` was confirmed at once; `status` showed no instances at 11:29:32, and `/info` says `deleted`. **Final cost $0.70** (active 11:13:50 to 11:29:21 at $2.70/hr). **Phase 5: $0.70 of $5.**
- [x] 3.5 Write the results down where people will look:
  - a `NOTES.md` entry with the multi-GPU numbers beside the single-A100 numbers, and the link type;
  - the README section updated from "not measured yet" to the measured verdict;
  - a short GUIDE Part 13: when tensor parallelism is worth it, compared with running two single-GPU VMs behind the gateway.

  Verify every number comes from 3.2–3.4.

## 4. Integration checks

- [x] 4.1 Verify the single-GPU path end to end against the fakes:
  - `up` with no option produces the same flags, the same script and the same offers as phase 4;
  - the phase 4 flag check against `deploy.py` at `68cff7e` still gives 15 identical arguments;
  - `git diff --quiet ee16ce7 -- deploy.py` succeeds.
  - **Result (2026-10-04, after the paid run):**
    - all three test files pass, including the byte-for-byte comparison of the one-GPU scripts with phase 4's;
    - the one-GPU flags equal the 15 arguments from `deploy.py` at `68cff7e`;
    - `deploy.py` is unchanged since `ee16ce7`.
- [x] 4.2 Scan every new and changed file for `SHADEFORM_API_KEY`, `VLLM_API_KEY` and the Modal token, and verify there are no matches before the operator is asked to approve a commit.
  - **Result (2026-10-04):** 24 new or changed files, including GuideLLM's result JSON: **0 matches** for the Modal token, `SHADEFORM_API_KEY` and `VLLM_API_KEY`. Re-run it right before committing if anything changes.
