# Proposal

## Why

`shadeform_deploy.py` can only start a VM with **one** GPU. The operator wants
the choice to be theirs: use the normal one-GPU command most of the time, and
switch on **tensor parallelism** (one model split across the two GPUs of a
single VM) when a run needs more speed or room, without touching anything else.

Two reasons to want it, both from phase 3's measurements:
- **KV cache room.** One A100 held 1,072,674 tokens of KV cache (4.29 full 250K requests). With the weights split in half per GPU, two 80 GB cards should hold roughly three times that, so more people can send long prompts at once.
- **Compute.** Phase 3 found the GPU compute-bound up to about 16 simultaneous requests. A second GPU doubles the compute available.

Neither gain is measured on this setup yet. Shadeform now lists a usable pair
(MassedCompute 2x A100 80GB, $2.70/hr, CUDA 13.0, no NVLink), so a test is
possible. This change makes it a **choice** and finds out, with one paid run,
what it really gives.

## What Changes

- **A new option on `up` and `offers`: `--tensor-parallel N`** (default 1).
  - With 1, or no option, **nothing changes**: the same offers, the same VM, and a vLLM command that is byte for byte today's. The check against `deploy.py` at `68cff7e` stays true.
  - With N more than 1, only **VMs with exactly N GPUs** are offered (each with enough memory), and vLLM is started with `--tensor-parallel-size N`.
  - It combines with the existing `--gpu`, `--cloud`, `--region` and `--hours`.
- **The option is named `--tensor-parallel`, not `--gpus`,** because `--gpu H100` already means the GPU *type*, and `--gpus 2` would look almost the same and mean something else.
- **A GPU-count check on the VM.** The startup script fails loudly if the VM shows fewer GPUs than requested, instead of letting vLLM start on fewer and fail confusingly. The tool then deletes the VM as it does for any failed start.
- **Container settings for multi-GPU,** found by testing. At least the shared memory may need to be larger than today's 16 GB, because the GPUs exchange data through it. Single-GPU runs keep today's settings.
- **The READY output and the startup log** state how many GPUs are in use and how they are connected (`nvidia-smi topo`), so a result can be read as "PCIe" or "NVLink".
- **Tests (free):** the offer filter, the generated script for N=1 and N=2, the GPU-count check, and the refusal when no N-GPU offer exists, all against fakes.
- **One paid measurement,** with the operator's approval: the same decode and capacity numbers as on one A100 (77.5 tokens/s, 38.33 GiB / 1,072,674 tokens of KV cache), plus the eval check and a tool call.
- **Docs:** README and GUIDE explain when each mode is worth it, with the measured numbers once they exist.

**Not in this change:**
- **Several VMs at once** (replication behind the gateway). It already works today by running `up` twice and giving both the same public name in the gateway. It needs no code.
- **Cards under 80 GB** (the $1.14 pair of 48 GB A6000s). Cheaper, but with much slower memory; a later experiment if wanted.
- **More than one VM per tensor-parallel group,** and 4 or 8 GPUs. The option accepts any N the offers can satisfy, but only N=2 is tested.
- **`deploy.py` (Modal)** is not touched.

## Capabilities

### New Capabilities
- `multi-gpu-serving`: running the model across the GPUs of one Shadeform VM when the operator asks for it, while a run without the option behaves exactly as before. It covers choosing matching offers, starting vLLM with the split, verifying the GPUs on the VM, and reporting how they are connected.

### Modified Capabilities
- None as spec deltas. The earlier requirement "only single-GPU offers" lives in the `shadeform-deployment` change, which has not been synced to `openspec/specs/` (no main specs exist, as in every earlier phase). The new capability states the relaxation itself: one GPU stays the default, and N GPUs are offered only on request.

## Impact

- **`shadeform_deploy.py`:** the offer filter, the vLLM flag list, the startup script, the plan and READY output, and the argument parser. The single-GPU path must stay identical.
- **`tests/`:** new cases in the offers, script and lifecycle tests, and a sample offer set that includes multi-GPU types.
- **`README.md`, `GUIDE.md`, `NOTES.md`:** the new option, and the measured results.
- **No new dependencies, no new secrets.** The tool stays standard library only.
- **Cost:** the free work costs nothing. The paid test is one 2x A100 VM at $2.70/hr: about 20 minutes to start plus about 25 minutes of measuring (including phase 3's 8-people-at-once test), so **about $2.00**, **at most $2.97** (the auto-delete spend limit for a 1-hour deadline). The phase ceiling is assumed to be **$5** of Shadeform credit, the same as phase 4; the operator can change it. A start that fails is deleted by the tool and costs about $0.50–1.
- **Risks, not yet known:**
  - **The model, MTP and the FP8 KV cache together on 2 GPUs** have never run. vLLM documents tensor parallelism for this model family, but the first run may need a flag change.
  - **No NVLink** on any offered pair, so the GPUs talk over PCIe and the speedup may be small.
  - **A longer start** than 15 minutes is possible (two worker processes to compile and warm up).
- **Availability is a market fact:** a usable pair is there today and may not be tomorrow. The tool already tells the operator when no offer fits.
- **Branch:** `phase-5-shadeform`, from the end of phase 4. The phase 4 change (`shadeform-deployment`) is still open with two tasks, and is left as it is.
