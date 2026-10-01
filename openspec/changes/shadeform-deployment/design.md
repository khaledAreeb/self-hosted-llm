# Design

## Context

See `proposal.md` for why; requirements are in `specs/shadeform-serving`.

**Verified on 2026-09-30,** from Shadeform's docs (`docs.shadeform.ai/llms-full.txt`),
its live API and the Docker registry. **Corrected on 2026-10-01** from the API
reference pages, which list request fields the guides leave out:

| Fact | Source |
|---|---|
| Auth is an `X-API-KEY` header; base `https://api.shadeform.ai/v1` | docs |
| `GET /instances/types` is public and returns every offer with `hourly_price` (cents), `availability[].available` per region, `configuration.os_options`, `vram_per_gpu_in_gb`, `num_gpus` | live API (no key needed) |
| `POST /instances/create` takes `cloud`, `region`, `shade_instance_type`, `shade_cloud: true`, `name`, `os`, `ssh_key_id`, and `launch_configuration` of type `docker` (`image`, `args` as one string, `envs: [{name, value}]`, `port_mappings: [{host_port, container_port}]`, `volume_mounts`, `shared_memory_in_gb`) or `script` (a base64 bash script). One or the other, not both. It returns `{id}` and works asynchronously | docs, API reference |
| **Auto-delete exists:** create also accepts `auto_delete: {date_threshold, spend_threshold}` (an RFC 3339 time, and a dollar amount), "to automatically delete the instance", and `/info` echoes it back. The guides never mention it, which is why the first version of this design said there was none. **Not yet seen working** | API reference (create, info) |
| `GET /instances/{id}/info` returns `status` (`creating` → `pending_provider` → `pending` → `active`, or `error`; then `deleting` → `deleted`), `ip`, `ssh_user`, `hourly_price` (cents), `cost_estimate` (dollars, as a string), `boot_time` (typically 300–600 s). **Billing stops when the status reaches `deleting`.** It also echoes `launch_configuration`, so the startup script is readable by anyone holding the account's API key | docs, API reference |
| `POST /instances/{id}/delete`, `GET /instances` | docs |
| **The status is the VM's, not the container's**; container progress is visible only over SSH (`journalctl -u init-script`, `docker logs`) | docs |
| **No firewall** in the platform (the docs point to UFW on the VM) | docs |
| Capacity can vanish between listing and creating; the docs say to try the next offer | docs |
| `vllm/vllm-openai:v0.30.0`: entrypoint `["vllm","serve"]`, **CUDA 13.0.2**, 8.7 GB compressed | Docker registry |
| Suitable A100 offers today: MassedCompute $1.38/hr (`ubuntu22.04_cuda13.0_shade_os`), Crusoe $2.00 (`cuda12.2`), Denvr $1.50 (`cuda12.4`); only 7 of 37 single-GPU 80 GB+ types were available at once | live API |

**From the codebase:** `deploy.py` builds the vLLM command inside `serve()`.
Most values are named settings, but some are written inline
(`--reasoning-parser qwen3`, `--enable-auto-tool-choice`, host and port).
`deploy.py` must stay unchanged (operator requirement), and the new tool must
not depend on it.

## Goals / Non-Goals

**Goals:**

- One command to open the model and one to close it, with nothing that can keep billing unnoticed.
- Byte-for-byte the same vLLM serving flags as the measured Modal deployment.

**Non-Goals:**

- **Scale-to-zero, or starting automatically on a request.** The operator opens and closes it, as agreed.
- **Keeping the model between VMs** with provider volumes. That locks the tool to one provider and region, which fights the "cheapest available" choice. The 28 GB download on each start is accepted; revisit only if starts prove too slow.
- **A stable hostname, DNS or Cloudflare.** The address changes on every `up`, and the gateway's API Base is updated by hand. The tool prints it.
- **Updating LiteLLM automatically** through its admin API. That's possible later; the admin key should not live in this tool yet.
- **Multi-GPU or other models.** One GPU, the model in `deploy.py`.
- **Retiring Modal.** `deploy.py` keeps working as a fallback.

## Decisions

### Settings live in the tool: standalone by design

`shadeform_deploy.py` is **fully standalone** (operator requirement): it
imports nothing from `deploy.py`, needs no `modal` package, and uses only the
Python standard library. Its serving settings are constants at the top of
the file, each with a short comment saying what it does and that it was
measured on Modal in phases 1–3:

```
MODEL_ID               = "Qwen/Qwen3.8-27B-FP8"
MAX_MODEL_LEN          = 250_000
KV_CACHE_DTYPE         = "fp8"
GPU_MEMORY_UTILIZATION = 0.90
REASONING_PARSER       = "qwen3"
CHAT_TEMPLATE_KWARGS   = '{"reasoning_effort": "low"}'
TOOL_CALL_PARSER       = "qwen3_xml"         # with --enable-auto-tool-choice
SPECULATIVE_CONFIG     = '{"method": "mtp", "num_speculative_tokens": 3}'
VLLM_IMAGE             = "vllm/vllm-openai:v0.30.0"
```

**At delivery, one check** confirms that these produce the same vLLM flags,
in the same order, as `deploy.py`'s `serve()` at commit `68cff7e`. It is done
by reading that file in git, and recorded in the change. It is a one-time
check, not a permanent test: after delivery the two deployments are
deliberately independent, so a Shadeform-specific tuning is not reported as
a failure.

*Alternatives considered:*
- **Importing `deploy.py`'s settings,** the previous plan. Rejected by the operator: it ties the tool to the Modal file and the `modal` package.
- **A permanent drift test** would fail every time one side is tuned on purpose. The settings are meant to be independent from now on.

**Benefit:** the tool runs anywhere Python 3 exists. That includes the gateway
server, which is where `reap` should run on a schedule.

### Both stages use the startup-script launch (changed during apply, 2026-10-01)

**First plan:** Docker launch for stage A. **Changed because** Docker launch
takes all vLLM arguments as **one `args` string**, and two of ours are JSON
with quotes and spaces (`{"reasoning_effort": "low"}`, the MTP config). The
docs don't say how Shadeform splits that string, and a wrong guess costs a
paid boot.

The startup-script launch (`type: script`, `script_configuration.base64_script`,
run once the VM is active, encrypted at rest; documented) lets us write the
exact `docker run` command ourselves, with every argument quoted by Python's
`shlex.quote`. The generated script can be **run on the laptop with fake
`docker`/`ufw`/`openssl` commands**, which prove exactly what vLLM would
receive, at $0.

The script, for both stages:
1. Logs to `/var/log/qwen38-start.log`, with timestamps and `nvidia-smi` driver output, so a failed start can be read over SSH.
2. **Stage B only:**
   - makes a self-signed certificate with `openssl`;
   - sets UFW to deny incoming except SSH (22) and 8443, after a `ufw --force reset`. The reset was added after the first stage B VM, whose MassedCompute image already allowed port 80.
3. `docker pull vllm/vllm-openai:v0.30.0`, then `docker run -d --gpus all --shm-size 16g --restart unless-stopped`, with:
   - `-p 8000:8000` (stage A) or `-p 8443:8443` plus the certificate directory mounted read-only (stage B);
   - `-v <host cache>:/root/.cache/huggingface`;
   - `-e VLLM_API_KEY`, `-e HF_HUB_DISABLE_XET=1`;
   - then the image and `MODEL_ID --port <port> <flags>` (stage B adds `--ssl-keyfile --ssl-certfile`).

Notes:
- **`VLLM_API_KEY`** is read by vLLM as its API key, so every request needs `Authorization: Bearer <key>`. That's the same header shape as the Modal proxy token, so the gateway entry keeps its format.
- **`HF_HUB_DISABLE_XET=1`** is the phase 1 lesson: Xet once left a download that "succeeded" with nothing in it.
- **Docker-published ports bypass UFW** (Docker writes its own iptables rules). That's why stage B publishes **only** 8443: there's nothing else to bypass, and UFW protects every other host port.
- **Assumption, verified in group 6:** Shadeform's `shade_os` images include Docker with GPU support, which their own Docker launch relies on. The script logs `docker info` and fails loudly if `--gpus` is unavailable.

**Self-signed TLS (stage B):** the tool prints the certificate fingerprint
it sees on the first connection. The gateway accepts the self-signed
certificate (`ssl_verify: false` for this model). **In LiteLLM this works only with
the vLLM provider (`hosted_vllm/`)**, found 2026-10-01: the `openai` provider goes
through the OpenAI SDK and ignores a per-model `ssl_verify`, so the gateway still
verified the certificate and dropped the connection. That stops eavesdropping,
but it doesn't verify the server's identity against an active
man-in-the-middle, which needs a real certificate and domain (a non-goal
here).

### Choosing an offer: filters first, then price

An offer is used only if:
- it has **1 GPU with at least 80 GB** of GPU memory;
- it is **available now** in some region;
- **the host driver can run the CUDA 13.0 container:** the chosen `os` option must be `cuda13.*` or newer.

Offers with older CUDA images are listed separately as *not usable*, with the
reason, so the operator sees why a cheaper-looking one was skipped. Then:
- **order by `hourly_price`;**
- **filter by region or cloud** with `--region` and `--cloud` (for example, EU only);
- **filter by GPU** with `--gpu` (for example `H100`), matching any part of the GPU or instance type. This was added during apply, at the operator's request, to try a stronger GPU than the cheapest one;
- **on a capacity error at create, try the next offer,** up to 3, and stop.

*Alternative:* try old-driver hosts with CUDA forward compatibility. Rejected:
the image sets `VLLM_ENABLE_CUDA_COMPATIBILITY=0`, and a failed boot costs
money and 15 minutes.

### Readiness is a real completion, and failure deletes the VM

`up` polls `/instances/{id}/info` until `active` and the IP is set. It then
polls `GET http://<ip>:8000/v1/models`, with the key, every 15 seconds. Once
that answers, it sends one short chat completion, and only when a real answer
comes back does it print the endpoint.

- **Time limit:** 40 minutes from create (boot up to 10 + image 8.7 GB + model 28 GB + vLLM start).
- **Past the limit, or on `status: error`:** the VM is deleted, the tool waits until Shadeform reports it `deleting` or `deleted`, and it prints the last known stage. Shadeform's docs say billing stops at `deleting`, so that status counts as the confirmation; the instance list keeps showing it until it is gone.
- **Ctrl-C during `up`** also deletes. Stopping the tool must never leave a VM billing.

### The deadline: Shadeform deletes the VM itself, and `reap` is the backup

`up --hours N` is required, and there is no default. The deadline is enforced
three independent ways:

1. **Shadeform's own auto-delete** (changed during apply, 2026-10-01). The create request carries:
   - `auto_delete.date_threshold` set to the deadline;
   - `auto_delete.spend_threshold` set to hours × hourly price + 10%, as a second trigger.

   This runs on Shadeform's side: no key on the VM, and nothing of ours has to be running.
2. **The deadline in the instance name,** `qwen38-until-<UTC time, e.g. 20260930T1900Z>`, enforced by `reap`. This is the backup while auto-delete is unproven (group 6), and stays as a cheap second check after that:
   - `reap` lists every instance whose name starts with `qwen38-until-`, deletes those past their deadline, and confirms each deletion; anything else on the account is ignored;
   - **no local state:** any machine with the Shadeform key can run `reap`, from a cron entry every 15 minutes on an always-on host (for example, where the gateway runs), or by hand.
3. **`up` deletes the VM on every failure path** (see above).

**`status`** shows time left and cost so far for the same instances.

*Alternative:* a watchdog on the VM that deletes itself. Rejected: it would
need the account-wide Shadeform key on the VM, and the key would then sit on
a machine exposed to the internet. Shadeform's auto-delete does the same job
without that.

### Secrets

| Secret | Where it lives | Where it goes |
|---|---|---|
| `SHADEFORM_API_KEY` | `.env` only (git-ignored) | sent only in the `X-API-KEY` header |
| `VLLM_API_KEY` | `.env` only; the tool generates it if absent and tells the operator to put it in the gateway | sent to Shadeform inside the startup script (`/info` returns it to anyone with the account key) and to the VM, where it lives in a root-only env file read by `docker run --env-file` |

The tool never prints either secret. The pre-commit secret scan from earlier
phases covers the new keys.

## Risks / Trade-offs

- **[Offers disappear between listing and creating]** → The tool retries the next offer, up to 3, and reports clearly when none work. Availability is a market fact, not a bug.
- **[Slow starts, ~15–25 min, paid]** → Accepted; recorded honestly in the docs. Revisit volumes only if measured starts are much worse.
- **[Plain HTTP in stage A exposes the key and prompts]** → A loud warning on every stage-A `up`; stage B is required before company data; the key is per-deployment and can be rotated in `.env`.
- **[Self-signed TLS doesn't prove the server's identity]** → It stops eavesdropping, which is the realistic threat here. A domain and real certificate are the upgrade path, and are out of scope.
- **[A forgotten VM keeps billing]** → A mandatory deadline, enforced by Shadeform's auto-delete and by `reap`, plus deletion on every failure path. The residual risk is a VM up to its deadline, which is bounded by what the operator typed.
- **[Auto-delete is documented but unproven]** → `reap` stays as an independent backup; group 6 checks that `/info` holds the threshold.
- **[Settings differ from Modal by accident]** → The one-time check at delivery makes the starting point identical. Later differences are deliberate: each file documents its own values. `deploy.py` is never edited, so this change cannot break the Modal endpoint.
- **[The first real boot on an unknown provider fails in a new way]** → The fatal-log lesson again: during `up`, the tool keeps its last-seen stage and, on failure, suggests the SSH command to read `journalctl` and `docker logs`.
- **[Data location]** → Most offers are in the US, as with Modal. `--region` lets the operator restrict it.

## Migration Plan

1. Add `shadeform_deploy.py` with its own settings; check them once against `deploy.py` at `68cff7e`; verify `git diff deploy.py` is empty.
2. Test `offers` against the live public API, with no key and no cost.
3. Have the operator create a Shadeform account with a few dollars of credit, and put `SHADEFORM_API_KEY` in `.env`.
4. Stage A: one real `up` → gateway test → `down`, about $1–2.
5. Stage B: one real `up --https` → gateway test → `down`.

**Rollback:** delete `shadeform_deploy.py` and its tests. `deploy.py` was
never touched, so Modal is unaffected at every step.
