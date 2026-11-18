# Runbook: Shadeform (rented VMs)

[← Back to the README](../README.md)

[`shadeform_deploy.py`](../shadeform_deploy.py) runs the same model, with the
same vLLM settings, on a GPU VM rented through Shadeform's marketplace. It is
standalone: plain `python3`, no packages, no `modal`. `deploy.py` is untouched,
and the Modal endpoint stays ready as a fallback.

How the script works inside, section by section, is in
[SHADEFORM_CODE_GUIDE.md](SHADEFORM_CODE_GUIDE.md). Measured results are in
[NOTES.md](NOTES.md), "Phase 4" and "Phase 5".

**The big difference from Modal: a VM bills from `up` until it is deleted,**
whether anyone uses it or not. So you open it when the team needs it, and you
close it afterwards. Every VM also gets a deadline when it is created:
- **Shadeform's own auto-delete** removes the VM at the deadline;
- **`reap`** deletes anything past its deadline, as a backup;
- **`up` deletes the VM itself** if the model never starts, if the VM reports an error, or if you press Ctrl-C.

## What you need first

1. **A Shadeform account with a few dollars of credit.** One test costs about $1–2. The account is the company workspace, so the tool only touches instances named `qwen38-until-*`.
2. **A dedicated API key.** Create a new one under Settings → API keys, not the Default key, and add it to `.env` (already git-ignored):
   ```
   SHADEFORM_API_KEY=<your key>
   ```
3. **The key vLLM will require.** `VLLM_API_KEY` is generated and added to `.env` on the first `up`; the tool never prints it. To choose your own, add `VLLM_API_KEY=<16+ characters, no spaces>` first.
4. **To read logs over SSH (optional):**
   - download the "Shadeform Managed Key" from Settings → SSH Keys;
   - or register your own key and pass `--ssh-key-id <id>` to `up`.

## The commands

**`offers`** (free) lists GPUs that can run the model now, cheapest first:
```bash
python3 shadeform_deploy.py offers
```
```
Usable now (1 GPU, 80 GB+, host CUDA 13.0+), cheapest first:
    $/hr  type               provider        region             OS image
    1.38  A100_sxm4_80G      massedcompute   desmoines-usa-1    ubuntu22.04_cuda13.0_shade_os
    2.73  H100               massedcompute   desmoines-usa-1    ubuntu22.04_cuda13.0_shade_os

Not usable (the vllm/vllm-openai:v0.30.0 image needs a CUDA 13.0+ host driver):
    1.35  A100_80G           hyperstack      montreal-canada-2  newest host CUDA is 12.8
    1.50  A100_sxm4_80G      denvr           houston-usa-1      newest host CUDA is 12.4
```
That listing is real (2026-10-01, shortened). "Not usable" offers look cheaper
but run older NVIDIA drivers, which can't start the pinned vLLM container.
- **Filters:**
  - `--gpu H100` matches any part of the GPU or instance type, to pick a stronger GPU than the cheapest;
  - `--region france` matches any part of the region name;
  - `--cloud massedcompute` matches the provider exactly;
  - `--tensor-parallel 2` lists VMs with exactly 2 GPUs instead of 1 (see [Two GPUs on one VM](#two-gpus-on-one-vm-tensor-parallelism)).
- **Applies to `up` too:** all these flags work there as well.

**`up`** (PAID from the moment the VM is created) shows the plan, asks before
creating, and finishes only when the model has answered a real question:
```bash
python3 shadeform_deploy.py up --hours 1            # stage A: plain HTTP, tests only
python3 shadeform_deploy.py up --hours 1 --https    # stage B: HTTPS + firewall
```
- **`--hours` is required:** fractions are allowed, up to 24.
- **`--yes`** skips the question, for scripts.
- **If an offer has no capacity,** it tries the next one, up to 3.
- **When it's ready,** it prints the gateway settings and the `down` command:
```
READY after 18m20s: the model answered 'ready'.

Gateway (LiteLLM) settings for this model:
  API Base            http://<ip>:8000/v1
  API Key             the VLLM_API_KEY value in .env (not printed here)
  Provider / Model    vLLM (hosted_vllm) / Qwen/Qwen3.8-27B-FP8
  Timeout             900 s

Close it when you are done; billing stops at once:
  python3 shadeform_deploy.py down <id>
```
Before printing READY it also checks that a request **without** the key is
refused, and in `--https` mode that plain HTTP and port 8000 are closed. If
any check fails, the VM is deleted.

**`status`** (free) lists this tool's VMs, with IP, price, cost so far and
time left. A VM past its deadline is shown as `OVERDUE`:
```bash
python3 shadeform_deploy.py status
```

**`down`** deletes the VM and confirms that Shadeform has stopped billing.
With no id, it deletes the tool's only running VM. If several are running, it
refuses and lists them:
```bash
python3 shadeform_deploy.py down
python3 shadeform_deploy.py down <id>
```

**`reap`** deletes every VM from this tool that is past its deadline, and
nothing else. Run it on a schedule on an always-on machine, such as the
gateway server. That machine needs only this file and a `.env` with
`SHADEFORM_API_KEY`:
```
*/15 * * * * cd /opt/deploy-llm && /usr/bin/python3 shadeform_deploy.py reap >> reap.log 2>&1
```

## Two GPUs on one VM (tensor parallelism)

**Optional, and off by default.** Without `--tensor-parallel`, nothing
changes: one GPU, exactly the setup measured in phases 1–4. With it, `up`
rents a VM with exactly that many GPUs and vLLM splits the model across them
(`--tensor-parallel-size`):
```bash
python3 shadeform_deploy.py offers --tensor-parallel 2                  # free: 2-GPU VMs, whole-VM price
python3 shadeform_deploy.py up --hours 1 --tensor-parallel 2 --gpu A100 # PAID: one VM, model on both GPUs
```
- **Live today (2026-10-04):** MassedCompute 2x A100 80GB at $2.70/hr (twice one A100), and Scaleway 2x H100 at $6.60/hr. Both are linked by **PCIe, no NVLink**. The `offers` listing and the READY output show the link.
- **Always add `--gpu A100`** (or the type you mean). If the first offer has no capacity, `up` tries the next cheapest **2-GPU** offer, which today is the $6.60 H100 pair.
- **Each GPU must have 80 GB or more,** the same rule as one GPU, so the cheap 48 GB pairs are not offered.
- **The other guarantees are unchanged:** the deadline and spend cap (priced for the whole VM), the key, `--https`, deletion on failure, `down`, `reap`.

**Measured on 2026-10-04: not worth it on today's offers.** The only usable
pair (MassedCompute 2x A100, PCIe through the CPU, no GPU peer-to-peer) was
compared with one A100:

| | 1x A100, $1.38/hr | 2x A100 tensor parallel, $2.70/hr |
|---|---|---|
| 8 people at once: first word p50 / p95 | **13.3 / 23.6 s** | 20.8 / 35.0 s |
| 8 people at once: writing speed | **75 / 66 tok/s** | 49 / 43 tok/s |
| one person alone | 77.5 tok/s | 82.9 tok/s |
| KV cache room | 1.07M tokens | **2.93M tokens** |

- **Two GPUs were slower for 8 people at once,** at twice the price, because without a direct link between them every token's work crosses the CPU.
- **The only gain** is room for many very long prompts at once.
- **To serve more people,** prefer two single-GPU VMs behind the gateway (`up` twice, the same public name). A pair with NVLink might change the result; none was offered.
- **Details:** `NOTES.md`, "Phase 5".

## Stage A and stage B

| | Stage A: `up` | Stage B: `up --https` |
|---|---|---|
| Use for | tests and demos with **non-sensitive** questions | anything with company data |
| Traffic | **plain HTTP: the key and every prompt are readable** on the way | encrypted (TLS, self-signed certificate) |
| Open ports | everything the provider leaves open | SSH and 8443 only (UFW firewall) |
| API Base | `http://<ip>:8000/v1` | `https://<ip>:8443/v1` |

**The self-signed certificate stops eavesdropping, but it isn't checked
against a certificate authority.** `up --https` prints the certificate's
SHA-256 fingerprint. To be sure you're talking to your VM, compare it over SSH
with `openssl x509 -in /opt/qwen38/tls/cert.pem -noout -fingerprint -sha256`.

## Connecting the gateway

The address changes on every `up`, so update the model's **API Base** each time.
The other settings stay the same:

```yaml
  - model_name: Qwen3.8-27B-FP8
    litellm_params:
      model: hosted_vllm/Qwen/Qwen3.8-27B-FP8   # the vLLM provider, not openai/ (see below)
      api_base: http://<ip>:8000/v1        # stage B: https://<ip>:8443/v1
      api_key: os.environ/QWEN_VM_KEY      # the VLLM_API_KEY value from .env
      timeout: 900
      stream_timeout: 900
      ssl_verify: false                    # stage B only: the certificate is self-signed
```

**Use the vLLM provider (`hosted_vllm/`), not `openai/`.** LiteLLM's `openai`
provider ignores a per-model `ssl_verify`, so in stage B the gateway rejects the
self-signed certificate. The symptom is "Connection error" in the gateway and a
500 in Copilot, while vLLM's log shows no request arriving. This was measured on
2026-10-01.

In the gateway's web form, these are the same fields:
- Provider: **vLLM**;
- API Base;
- API Key;
- the model name `Qwen/Qwen3.8-27B-FP8`.

Copilot and OpenCode don't change, because they talk to the gateway.

Background health checks don't add cost here, because the VM bills anyway.
But while the VM is closed they fail, and the gateway may mark the model
unhealthy. That's expected.

## What a start costs, and how long it takes

**Measured on 2026-10-01, on one A100: about 15 minutes from `up` to READY**
(details in `NOTES.md`):
- the VM boots in about 3 minutes;
- the 8.7 GB container downloads in about 2;
- the 28 GB model downloads in 3–4.5, every time, because nothing is kept between VMs;
- vLLM starts in about 4.

You pay for those minutes: about $0.34 per start on the $1.38/hr A100. A
2-GPU start took 11.5 minutes from active to READY, but the provider took 10
minutes to start that VM (not billed).

## If a start fails

`up` deletes the VM, so look while it's starting. Once the VM is active, `up`
prints its IP. Then, in another terminal:
```bash
ssh shadeform@<ip> 'tail -f /opt/qwen38/start.log'   # the startup script, step by step
ssh shadeform@<ip> 'sudo docker logs -f qwen38'      # vLLM itself
ssh shadeform@<ip> 'sudo journalctl -u init-script'  # Shadeform's view of the script
```
- **`FATAL: driver ... too old`:** the host can't run the CUDA 13 image. `offers` should have excluded it, so report it.
- **`Shadeform's VM has 1 GPU(s), 2 were requested`** (with `--tensor-parallel`): Shadeform handed over a different machine. `up` deletes it at once, seconds after creating it.
- **`FATAL: 2 GPUs requested, 1 found`** in `start.log`: the VM itself shows fewer GPUs than it should. vLLM never starts, and `up` deletes the VM at its start limit.
- **How the GPUs are linked:** with `--tensor-parallel`, `start.log` holds the output of `nvidia-smi topo -m` (`NV#` means NVLink; `PHB`, `PXB` or `SYS` mean PCIe).
- **The container keeps restarting:** read `docker logs`. On Modal, the H100 failed exactly like this.

## Tests (free)

```bash
python3 tests/test_shadeform_offers.py      # offer filtering, from a saved sample
python3 tests/test_shadeform_script.py      # the VM's startup script for 1 and 2 GPUs, run with fake docker/ufw/nvidia-smi
python3 tests/test_shadeform_lifecycle.py   # every command against a fake Shadeform API and vLLM
```
