# Self-hosted Qwen3.8-27B

A private, OpenAI-compatible API for **Qwen3.8-27B** (`Qwen/Qwen3.8-27B-FP8`),
served by [vLLM](https://docs.vllm.ai) on one A100-80GB GPU. Prompts and
documents stay on infrastructure we control, which is why this exists. It is
not the cheapest way to use the model (see [What it costs](#what-it-costs)).

- **250K-token context**, image input (vision), and tool calls for agents.
- **Reasoning on at `low` effort** by default, adjustable per request.
- **Works with any OpenAI client**: Copilot, OpenCode, LangChain or `curl`, usually through the team's LiteLLM gateway.

---

## Two ways to run it

The model and the vLLM settings are the same in both. Choose by how busy the
GPU will be.

| | **Modal**, serverless: [`deploy.py`](deploy.py) | **Shadeform**, rented VM: [`shadeform_deploy.py`](shadeform_deploy.py) |
|---|---|---|
| You pay for | busy time, plus up to 60 idle minutes after each burst | every minute the VM exists |
| A100-80GB price | ~$2.94/hr | ~$1.38/hr |
| Starting | automatic on the first request: 5–10 min cold start | you run `up`: ready in ~15 min |
| Stopping | automatic after 60 idle minutes | you run `down`, with a hard deadline as backup |
| Address | one fixed HTTPS URL | a new IP on every `up` |
| Good for | a few questions spread across the day | a team using it through a working session |

**Rule of thumb:** Shadeform is cheaper once the GPU is busy for more than
about half the hours it's open.

---

## Quick start

### 1. Use the model

If the model is already running, you don't need any of the tools in this
repo. Most people call it **through the team's LiteLLM gateway**: ask the
gateway owner for a key and the model name.

To call the Modal endpoint directly, you need a Modal proxy token
(`wk-...ws-...`) from the workspace owner:

```bash
curl https://dev-khaled-areeb--qwen38-27b-serve.modal.run/v1/chat/completions \
  -H "Authorization: Bearer $MODAL_PROXY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen3.8-27B-FP8",
       "messages": [{"role": "user", "content": "Say hello in one sentence."}]}'
```

**Before you rely on it:**
- **The first request after a quiet hour can take 5–10 minutes** while the GPU starts. Set client and gateway timeouts to **900 s**.
- **Allow enough `max_tokens`:** 4,000+ in general, 10,000+ for long documents. Reasoning counts against it, and too small a budget returns an empty answer.
- **Change reasoning per request:** `"chat_template_kwargs": {"reasoning_effort": "medium"}` for hard problems, or `{"enable_thinking": false}` for none.
- **Very long documents slow everyone down.** One ~137K-token read makes other users wait about 1.5 minutes, so keep huge documents for quiet times.
- **Check written reports.** Facts and numbers come out right, but the model adds plausible details that weren't in the source, such as weekdays and causes.

### 2. Run it on Modal

You need Python 3 and a Modal account.

```bash
cp .env.example .env                                         # secrets stay in .env, which is git-ignored
python3 -m venv venv && ./venv/bin/pip install modal
./venv/bin/modal setup                                       # log in
./venv/bin/modal workspace proxy-tokens create litellm-qwen  # put wk-...ws-... in .env as MODAL_PROXY_TOKEN
./venv/bin/modal run deploy.py::download                     # once: 28 GB of weights into a Modal Volume
./venv/bin/modal deploy deploy.py                            # free: nothing runs until the first request
```

Full runbook, including the gateway configuration: **[docs/MODAL.md](docs/MODAL.md)**.

### 3. Run it on Shadeform

You need Python 3 only (no packages), and a Shadeform API key in `.env` as
`SHADEFORM_API_KEY`.

```bash
python3 shadeform_deploy.py offers                  # free: usable GPUs, cheapest first
python3 shadeform_deploy.py up --hours 2 --https    # PAID from here; prints the API Base once the model answers
python3 shadeform_deploy.py status                  # free: what's running, cost so far, time left
python3 shadeform_deploy.py down                    # deletes the VM; billing stops
```

- **`--hours` is required** (24 at most). It is a safety deadline: Shadeform's auto-delete removes the VM then even if you forget `down`, with `reap` as a backup (auto-delete hasn't yet been seen firing).
- **Use `--https` for anything with company data.** Without it, traffic is plain HTTP.
- **Failed starts clean up after themselves:** `up` deletes the VM if the model never starts or you press Ctrl-C.

Full runbook: **[docs/SHADEFORM.md](docs/SHADEFORM.md)**.

### 4. Connect the LiteLLM gateway

- **Modal:** copy the config in [docs/MODAL.md](docs/MODAL.md#litellm-gateway-configuration) exactly. It turns off background health checks in three places; without them, the gateway's polling keeps the GPU awake for good (~$70 a day).
- **Shadeform:** use the **vLLM provider** (`hosted_vllm/`), not `openai/`, with the API Base that `up` prints. Add `ssl_verify: false` with `--https`. The address changes on every `up`. Details: [docs/SHADEFORM.md](docs/SHADEFORM.md#connecting-the-gateway).

---

## Rules that protect the budget

1. **Modal: never enable background health checks** for this model in LiteLLM. Check by billing, not by config: leave the gateway running overnight and confirm zero GPU cost.
2. **Modal: keep `max_containers=1`** unless a second GPU has a budget. A burst then waits for the one GPU instead of silently starting another.
3. **Shadeform: every `up` gets a `down`.** As a backup, run `reap` every 15 minutes on an always-on machine:
   ```
   */15 * * * * cd /opt/deploy-llm && /usr/bin/python3 shadeform_deploy.py reap >> reap.log 2>&1
   ```
4. **Never delete the Modal Volumes.** Storage is free, and deleting them costs a 28 GB re-download.
5. **Secrets live only in `.env`:** `MODAL_PROXY_TOKEN`, `SHADEFORM_API_KEY`, `VLLM_API_KEY`. The file is git-ignored; keep it that way.

---

## What to expect (measured)

| | Result | Source |
|---|---|---|
| **People at once** | ~10–20 chatting or coding (4 simultaneous requests within the 20 s first-word target), or up to 8 coding agents | [bench/FINDINGS.md](bench/FINDINGS.md) |
| **Answer quality** | 24 synthetic business tasks: 18 pass, 6 partial, 0 fail at `low`; 20 pass at `medium` | [eval/FINDINGS.md](eval/FINDINGS.md) |
| **By area** | coding 6/6, long documents 5–6/6, vision 5/6, report writing 2–3/6 (embellishes) | [eval/FINDINGS.md](eval/FINDINGS.md) |
| **Speed** | ~75 tokens/s per answer on short prompts, with MTP speculative decoding | [docs/NOTES.md](docs/NOTES.md) |
| **Long context** | 250K tokens; a 3-step lookup across 195K tokens answered correctly | [eval/FINDINGS.md](eval/FINDINGS.md) |
| **Two GPUs (tensor parallel)** | slower for 8 users at twice the price on today's PCIe pairs, so not recommended | [docs/NOTES.md](docs/NOTES.md), "Phase 5" |

## What it costs

- **Modal:** ~$2.94/hr while the GPU is up ($2.50 GPU plus $0.44 CPU and memory). Up to ~$2.94 of idle time follows each burst.
- **Shadeform:** $1.38/hr for an A100 while the VM exists, plus ~$0.34 for each 15-minute start.
- **A full 9-to-5 month** is ~195 GPU-hours: ~$570 on Modal, or ~$270 on Shadeform with the VM open all those hours.
- **For comparison,** the same model through a hosted API would likely cost $10–40 a month at our volume. Self-hosting buys data residency, not savings.

---

## Repository layout

```
deploy.py                  Modal app: image, weight download, vLLM server (every setting at the top, with its reason)
shadeform_deploy.py        Shadeform CLI: offers / up / status / down / reap (standard library only)
.env.example               the secrets each tool reads; copy to .env

docs/
  MODAL.md                 Modal runbook: setup, calling, gateway config, troubleshooting
  SHADEFORM.md             Shadeform runbook: commands, HTTPS, two GPUs, troubleshooting
  SHADEFORM_CODE_GUIDE.md  how shadeform_deploy.py works, section by section
  GUIDE.md                 lessons learned: how to deploy, measure and judge an LLM yourself
  NOTES.md                 dated log of every measurement, decision and dollar spent

eval/                      capability evaluation: 24 tasks, graders, results  ->  eval/FINDINGS.md
bench/                     load tests: how many people at once  ->  bench/README.md, bench/FINDINGS.md
tests/                     offline tests for shadeform_deploy.py (fake API, fake vLLM, no cost)
openspec/                  the plan for each phase (proposal, design, tasks); finished phases in archive/
```

## Tests

All offline and free: no network, no GPU.

```bash
python3 tests/test_shadeform_offers.py      # offer filtering, from a saved sample
python3 tests/test_shadeform_script.py      # the VM startup script, run with fake docker/ufw/nvidia-smi
python3 tests/test_shadeform_lifecycle.py   # every command against a fake Shadeform API and vLLM
python3 bench/tests/test_sampler.py         # the load-test metrics sampler
```

## If something goes wrong

| Symptom | Likely cause and fix |
|---|---|
| First request times out | Cold start. Raise client and gateway timeouts to 900 s. |
| `content: null` or an empty answer | Reasoning used the whole budget. Raise `max_tokens`. |
| `missing credentials for proxy authorization` | The caller isn't sending `Authorization: Bearer <MODAL_PROXY_TOKEN>`. |
| Modal bills GPU time overnight with no users | Gateway health checks are on. See [docs/MODAL.md](docs/MODAL.md#litellm-gateway-configuration). |
| Gateway shows "Connection error" for a `--https` VM | Use the `hosted_vllm/` provider with `ssl_verify: false`. |
| `shadeform_deploy.py up` fails | See [docs/SHADEFORM.md](docs/SHADEFORM.md#if-a-start-fails) for the logs to read over SSH. |

More: [docs/MODAL.md](docs/MODAL.md#if-something-breaks).

---

## How it was built

Five phases, each planned with [OpenSpec](openspec/) and logged in
[docs/NOTES.md](docs/NOTES.md). Total spend was about $27 of Modal credit and
$3.90 of Shadeform credit.

1. **Deploy on Modal:** an authenticated, scale-to-zero endpoint, wired to LiteLLM, Copilot and OpenCode.
2. **Judge the model:** 250K context verified, MTP speculative decoding (2.29x faster writing), and a 24-task evaluation.
3. **Load test:** how many people one A100 serves; FP8 KV cache doubled capacity.
4. **Rented VMs:** `shadeform_deploy.py`, at about half Modal's hourly price, with HTTPS and a firewall.
5. **Two GPUs:** tensor parallelism measured and rejected on today's hardware.

Want to do this yourself for another model? Start with [docs/GUIDE.md](docs/GUIDE.md).
