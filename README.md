# Qwen3.8-27B on Modal

An on-demand, authenticated, OpenAI-compatible endpoint serving
`Qwen/Qwen3.8-27B-FP8` with vLLM. It scales to zero when idle and starts only
for authorized requests.

Everything lives in one file: [`deploy.py`](deploy.py). Constants are at the top.

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

**Idle window is 5 minutes.** Modal's own example ships 15, which for a bursty
team is ~90 min/day of paid idle GPU. Do not drop below ~2 minutes: a user who
pauses 90 seconds to read an answer would otherwise trigger a cold start
mid-conversation.

## LiteLLM gateway configuration

> ### DO NOT ENABLE BACKGROUND HEALTH CHECKS FOR THIS MODEL
>
> LiteLLM polls every configured model every **300 seconds** by default. The
> idle window here is also 300 seconds, so polling holds the GPU awake
> permanently. At ~$2.94/hr that drains a $30 budget in roughly **10 hours with
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
