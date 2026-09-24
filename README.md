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

**Responses carry heavy reasoning overhead.** A request for "exactly one short
sentence" produced 47 reasoning tokens and 7 visible ones. Reasoning arrives in
a separate `reasoning` field, so it will not pollute `content`, but users do
wait for it.

---

## Operating notes

**Idle window is 5 minutes.** Modal's own example ships 15, which for a bursty
team is ~90 min/day of paid idle GPU. Do not drop below ~2 minutes: a user who
pauses 90 seconds to read an answer would otherwise trigger a cold start
mid-conversation.

**Do not enable LiteLLM background health checks for this model.** They poll
every 300 seconds by default, which holds the container permanently awake.
At ~$2.54/hr that exhausts a $30 budget in roughly 12 hours **with zero user
requests**. Three settings are required, because one is known to be
insufficient:

```yaml
general_settings:
  background_health_checks: false
  health_check_skip_disabled_background_models: true

model_list:
  - model_name: qwen3.8-27b
    litellm_params:
      model: openai/Qwen/Qwen3.8-27B-FP8
      api_base: https://dev-khaled-areeb--qwen38-27b-serve.modal.run/v1
      api_key: os.environ/MODAL_PROXY_TOKEN   # the wk-....ws-... bearer form
    model_info:
      disable_background_health_check: true
```

Verify suppression by leaving it idle overnight and checking the Modal billing
dashboard reads zero — configuration inspection alone cannot confirm it.

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
