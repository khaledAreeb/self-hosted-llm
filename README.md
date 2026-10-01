# Qwen3.8-27B on Modal

An on-demand, authenticated, OpenAI-compatible endpoint serving
`Qwen/Qwen3.8-27B-FP8` with vLLM. It scales to zero when idle and starts only
for authorized requests.

Everything lives in one file: [`deploy.py`](deploy.py). Constants are at the top.

**The same model can also run on a rented Shadeform VM**, at about half the
hourly price but with no scale-to-zero. That is a separate, standalone tool,
[`shadeform_deploy.py`](shadeform_deploy.py); see [Shadeform](#shadeform-rented-vms)
below. It does not change anything here.

The reasoning behind each choice is in
[`openspec/changes/deploy-qwen38-27b-modal-pilot/design.md`](openspec/changes/deploy-qwen38-27b-modal-pilot/design.md).
Running measurements and budget are in [`NOTES.md`](NOTES.md).

---

## One-time setup

```bash
# 1. Install and authenticate
./venv/bin/pip install modal
./venv/bin/modal setup
./venv/bin/modal profile current      # should print your workspace

# 2. Create a proxy auth token for each consumer
./venv/bin/modal workspace proxy-tokens create litellm-qwen
```

The secret (`ws-...`) is shown **once**. Store the pair as the combined bearer
form in a gitignored `.env`:

```
MODAL_PROXY_TOKEN=wk-<id>.ws-<secret>
```

Modal validates these at its **edge**, so the container never needs them — do
not put them in a Modal Secret. They belong wherever the *caller* runs.

```bash
# 3. Download the weights -- run ONCE (~28 GB into a Modal Volume)
./venv/bin/modal run deploy.py::download
```

Kept separate from serving on purpose: if the download happened on first boot,
any cache miss would re-pull 28 GB and bill for the transfer.

---

## Deploy

```bash
./venv/bin/modal deploy deploy.py
```

Modal prints the endpoint URL with a key icon next to it, confirming proxy auth
is on. Deploying costs nothing — no container starts until a request arrives.

The live endpoint is:

    https://dev-khaled-areeb--qwen38-27b-serve.modal.run

---

## Call it

```bash
source .env
curl https://dev-khaled-areeb--qwen38-27b-serve.modal.run/v1/chat/completions \
  -H "Authorization: Bearer $MODAL_PROXY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "model": "Qwen/Qwen3.8-27B-FP8",
        "messages": [{"role": "user", "content": "Say hello in one sentence."}]
      }'
```

Add `"stream": true` for incremental tokens.

**Expect a slow first request.** The measured first-ever cold start was
**602 seconds** (~10 min) on A100-80GB, which included one-off `torch.compile`
and CUDA graph capture now cached in the `vllm_cache` Volume. Later cold starts
should be faster; measure before relying on a shorter client timeout.

**Thinking is disabled by default.** This model ships with `xhigh` reasoning
effort, which made it unusable: a request for a 400-word explanation spent all
800 available tokens reasoning and returned `content: None`. The server now
sets `--default-chat-template-kwargs '{"enable_thinking": false}'`.

To get reasoning back for a hard question, ask for it per request — request-level
kwargs always beat the server default:

```json
{
  "model": "qwen3.8-27b",
  "messages": [{"role": "user", "content": "..."}],
  "chat_template_kwargs": {"enable_thinking": true}
}
```

Set this on the **vLLM side**, not in LiteLLM: `chat_template_kwargs` is a vLLM
extension rather than part of the OpenAI spec, so routing it through a proxy
means trusting that proxy to forward a non-standard field.

---

## Operating notes

**Idle window is 5 minutes** (was 10 from 2026-09-27 to 2026-09-30). Modal's own example ships 15, which for a bursty
team is ~90 min/day of paid idle GPU. Do not drop below ~2 minutes: a user who
pauses 90 seconds to read an answer would otherwise trigger a cold start
mid-conversation.

**How many people it serves (measured 2026-09-29, `bench/FINDINGS.md`).** One
A100 handles **4 simultaneous interactive requests** within target: 95% of
requests show their first visible word within 20 s. That is roughly **10–20
people** chatting or coding, and **up to 8 coding agents** at once. Past that,
nothing fails; answers get slower. At 8 simultaneous requests the first word
typically takes ~13 s and the slowest ~24 s.

**What users should expect at busy times:**
- **One long document stalls everyone.** While someone's ~137K-token document is being read (about 1.5 minutes), everyone else's first word can take up to ~100 s. Warn the team, or keep huge documents for quiet times.
- **Occasionally an empty answer.** The model can spend its whole budget thinking. Callers should allow `max_tokens` of 4,000+, and 10,000+ for document work.

**One container, never two.** `max_containers=1` means a burst waits for the
one GPU instead of silently starting a second A100 at full price. Raise it
deliberately, with a budget, if one GPU is measured to be too slow for the team.

**Serving config:** FP8 KV cache, MTP speculative decoding, thinking `low`.
Each was measured, not assumed; see the comments in `deploy.py`. To re-measure
capacity after any change, see `bench/README.md`.

## LiteLLM gateway configuration

> ### DO NOT ENABLE BACKGROUND HEALTH CHECKS FOR THIS MODEL
>
> LiteLLM polls every configured model every **300 seconds** by default. The
> idle window here is 300 seconds -- the same as the polling interval -- so
> polling holds the GPU awake permanently. At ~$2.94/hr that drains a $30 budget in roughly **10 hours with
> zero user requests** — and shortening the idle window makes it worse, not
> better, because each cycle then pays a fresh cold start.
>
> **Three** settings are required. One is not enough: there is an open LiteLLM
> defect where the internal health check still crawls configured models despite
> the per-model flag.

This is the verified working configuration:

```yaml
model_list:
  - model_name: qwen3.8-27b
    litellm_params:
      model: openai/Qwen/Qwen3.8-27B-FP8            # openai/ prefix + the name vLLM serves
      api_base: https://dev-khaled-areeb--qwen38-27b-serve.modal.run/v1
      api_key: os.environ/MODAL_PROXY_TOKEN         # the wk-....ws-... bearer form
      timeout: 900                                  # must exceed the cold start
      stream_timeout: 900
    model_info:
      disable_background_health_check: true         # suppression 3 of 3

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  background_health_checks: false                   # suppression 1 of 3
  health_check_skip_disabled_background_models: true  # suppression 2 of 3

router_settings:
  num_retries: 0        # a slow cold start must not multiply into containers

litellm_settings:
  num_retries: 0
  telemetry: False
```

Keep this in a **separate config file** if your gateway serves other models —
`num_retries: 0` applied globally would affect all of them.

**Timeout must exceed the cold start.** Measured cold starts: 602 s, then
514 s, then 428 s as the compile cache filled. 900 s leaves headroom. A shorter
timeout fails requests while the backend is starting perfectly normally.

**Verify suppression by billing, not by config.** Leave the gateway running
overnight with no user activity and confirm the Modal dashboard shows zero
GPU cost. Reading the config proves nothing — that is the whole point of the
check. Do **not** stop the Modal app to make this pass; stopping it would
conceal a polling defect rather than detect it.

**Reasoning appears as `reasoning_content`.** LiteLLM renames the model's
`reasoning` field to the conventional OpenAI-compatible name. With thinking
disabled by default this is usually empty, but clients that request thinking
per-request will receive it there rather than in `content`.

**Never delete the Volumes to save money.** Storage is free below 1 TiB and
these use ~33 GiB. Deleting saves nothing and costs a 28 GB re-download.

---

## If something breaks

| Symptom | Fix |
|---|---|
| Image fails to build | Adjust the CUDA tag in `deploy.py` |
| `A100-40GB` rejected at deploy | Try `A100-80GB` or `L40S` |
| Model loads but output is incoherent | Set `GPU = "L40S"` — the Ampere FP8-Marlin path is unverified against this model's DeltaNet layers |
| `unrecognized arguments: --reasoning-parser` | Drop that flag from `serve()` |
| Request fails while container is starting | Raise the caller's timeout above the cold start in `NOTES.md` |
| `missing credentials for proxy authorization` | The caller is not forwarding the bearer token |

---

## Shadeform (rented VMs)

[`shadeform_deploy.py`](shadeform_deploy.py) runs the same model, with the
same vLLM settings, on a GPU VM rented through Shadeform's marketplace. It is
standalone: plain `python3`, no packages, no `modal`. `deploy.py` is untouched,
and the Modal endpoint stays ready as a fallback.

**The big difference from Modal: a VM bills from `up` until it is deleted,**
whether anyone uses it or not. So you open it when the team needs it, and you
close it afterwards. Every VM also gets a deadline when it is created:
- **Shadeform's own auto-delete** removes the VM at the deadline;
- **`reap`** deletes anything past its deadline, as a backup;
- **`up` deletes the VM itself** if the model never starts, if the VM reports an error, or if you press Ctrl-C.

### What you need first

1. **A Shadeform account with a few dollars of credit.** One test costs about $1–2. The account is the company workspace, so the tool only touches instances named `qwen38-until-*`.
2. **A dedicated API key.** Create a new one under Settings → API keys, not the Default key, and add it to `.env` (already git-ignored):
   ```
   SHADEFORM_API_KEY=<your key>
   ```
3. **The key vLLM will require.** `VLLM_API_KEY` is generated and added to `.env` on the first `up`; the tool never prints it. To choose your own, add `VLLM_API_KEY=<16+ characters, no spaces>` first.
4. **To read logs over SSH (optional):**
   - download the "Shadeform Managed Key" from Settings → SSH Keys;
   - or register your own key and pass `--ssh-key-id <id>` to `up`.

### The commands

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
  - `--cloud massedcompute` matches the provider exactly.
- **Applies to `up` too:** both flags work there as well.

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

### Stage A and stage B

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

### Connecting the gateway

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

### What a start costs, and how long it takes

**Estimated, until the first paid run measures it:** 15–25 minutes from
`up` to READY:
- the VM boots in 5–10 minutes;
- the 8.7 GB container downloads;
- the 28 GB model downloads, every time, because nothing is kept between VMs;
- vLLM starts.

You pay for those minutes: about $0.35–0.60 per start on the $1.38/hr A100.
Measured numbers will go in `NOTES.md`.

### If a start fails

`up` deletes the VM, so look while it's starting. Once the VM is active, `up`
prints its IP. Then, in another terminal:
```bash
ssh shadeform@<ip> 'tail -f /opt/qwen38/start.log'   # the startup script, step by step
ssh shadeform@<ip> 'sudo docker logs -f qwen38'      # vLLM itself
ssh shadeform@<ip> 'sudo journalctl -u init-script'  # Shadeform's view of the script
```
- **`FATAL: driver ... too old`:** the host can't run the CUDA 13 image. `offers` should have excluded it, so report it.
- **The container keeps restarting:** read `docker logs`. On Modal, the H100 failed exactly like this.

### Tests (free)

```bash
python3 tests/test_shadeform_offers.py      # offer filtering, from a saved sample
python3 tests/test_shadeform_script.py      # the VM's startup script, run with fake docker/ufw
python3 tests/test_shadeform_lifecycle.py   # every command against a fake Shadeform API and vLLM
```
