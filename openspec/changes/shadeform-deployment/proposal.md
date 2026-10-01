# Proposal

## Why

The Modal deployment works and is measured, but Modal's price per GPU-hour is
high for a team pilot. An A100 costs ~$2.94/hr all-in on Modal, against
$1.38–2.00/hr on Shadeform's marketplace today (live `/instances/types`,
2026-09-30). The Modal trial budget is also nearly spent. Shadeform rents
whole VMs from many providers through one API, so the same model and vLLM
settings can run for roughly half the hourly price.

Shadeform has no scale-to-zero, and the operator accepts that: they will open
the VM when the team needs it and close it afterwards. What is missing is a
safe, repeatable way to do that. Opening must bring the model up with exactly
the settings measured in phases 1–3, and closing must actually stop the
billing. Nothing may keep running, and charging, because someone forgot it.

## What Changes

- **New `shadeform_deploy.py`** in the project root. It is a small
  command-line tool beside `deploy.py`. **`deploy.py` is not changed at all**
  (operator requirement, 2026-10-01): the Modal deployment stays exactly as
  measured and ready to use. The tool's commands:
  - `offers` lists the cheapest available GPUs that can run the model;
  - `up` creates a VM running vLLM and waits until the model actually
    answers;
  - `status` shows running instances and their cost so far;
  - `down` deletes the VM;
  - `reap` deletes any instance past its time limit.
- **Fully standalone** (operator requirement, 2026-10-01). The tool does not
  import `deploy.py` or need the `modal` package; it runs with plain `python3`
  on any machine. It **starts from the same measured settings** as the Modal
  deployment (250K context, FP8 KV cache, MTP, `low` thinking, tool calling),
  written into the tool itself and checked once, flag for flag, against
  `deploy.py` at delivery. After that the two are independent: either can be
  tuned without touching the other.
- **The official vLLM container,** pinned to `vllm/vllm-openai:v0.30.0` (the
  version measured on Modal). It replaces our custom image, and removes the
  CUDA-version problem that crashed the H100 on Modal.
- **Access protected by vLLM's API key.** A secret key is required on every
  request, and the tool prints the address and key settings for the gateway.
  - **Stage A (this change):** plain HTTP, for tests and demos with
    non-sensitive questions only.
  - **Stage B (this change):** HTTPS with a certificate generated on the VM,
    plus a firewall allowing only SSH and the API port, before any company
    data goes through it.
- **A hard time limit on every VM.** `up` requires a number of hours. The
  deadline is given to Shadeform's own auto-delete, which deletes the VM on
  Shadeform's side. It is also recorded in the instance's name, so `reap`, run
  on a schedule, deletes anything past it as a backup. Together they replace
  Modal's scale-to-zero as the safety net. (The first draft said Shadeform had
  no auto-delete; its API reference shows it does, corrected 2026-10-01.)
- **Operator documentation** for opening, closing, connecting LiteLLM and
  recovering from a failed start.

## Capabilities

### New Capabilities
- `shadeform-serving`: running the model on a rented Shadeform VM that the operator opens and closes. It covers choosing an available GPU, bringing the model up with the measured settings, protecting access, guaranteeing that billing stops, and giving the gateway what it needs to connect.

### Modified Capabilities
- None. No main specs exist in this project; every earlier phase was archived without syncing.

## Impact

- **New file** `shadeform_deploy.py`, using **only the Python standard
  library**. Nothing from the Modal deployment is imported.
- **`deploy.py`: no changes.** The Modal deployment remains ready as a
  fallback; every task verifies `git diff deploy.py` is empty.
- **New secrets in `.env`** (already git-ignored):
  - `SHADEFORM_API_KEY`, the operator's Shadeform key;
  - `VLLM_API_KEY`, the password the VM's vLLM will require.
- **Gateway:** after each `up`, the model's API Base in LiteLLM changes to the
  new VM's address. The tool prints the exact values to paste.
- **Cost:** you pay while the VM exists, including its ~15–25 minute start
  (boot, container download, 28 GB model download, vLLM start). A first
  end-to-end test is about 45–60 minutes on an A100 at $1.38–2.00/hr, so
  **about $1–2 of Shadeform credit**. That needs a Shadeform account with
  credit; the Modal budget is not used.
- **Data location:** most available GPUs today are in the US, as with Modal.
  One EU option exists (Paris). The tool lets the operator restrict regions
  if that matters.
