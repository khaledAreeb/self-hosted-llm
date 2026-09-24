# How to deploy an LLM on serverless GPU — what I learned doing it

A walkthrough of deploying Qwen3.8-27B on Modal, written so you can do the next
one yourself. It covers the *method* for each decision, not just the answer we
landed on, because the answers change with the model and the answers are the
easy part.

Five things went wrong along the way. Four of them reported success while being
broken. Those sections matter more than the happy path.

---

## Part 1 — The mental model

### What you are actually renting

```
  YOUR MACHINE            MODAL                         HUGGING FACE
  ============            =====                         ============
  deploy.py       ---->   builds a container image
                          runs it on a GPU when asked   <---- model weights
                          stops it when idle                  (downloaded once)
                             |
                             v
                          an HTTPS URL
```

Three things live in different places, and confusing them causes most early
mistakes:

| Thing | Where it lives | What it costs |
|---|---|---|
| Model weights | a Modal **Volume** (persistent disk) | free under 1 TiB |
| The running model | a **container** with a GPU attached | $2-4/hour, only while running |
| The endpoint URL | Modal's edge, always there | nothing |

The URL existing costs nothing. A container running costs money. Those are
separate, and that separation is the entire point of serverless.

### Why "scale to zero" is the whole game

A GPU rented by the hour costs the same whether anyone uses it. Serverless bills
only while a container is alive. Your bill becomes:

```
  monthly cost = (GPU $/hr) x (hours a container was actually alive)
```

The second term is called **duty cycle**, and nothing about your code predicts
it. It comes from how your team behaves. This is why a pilot exists at all: to
measure a number you cannot derive.

The tradeoff is the **cold start** — the first request after idle must wait for
the model to load. Ours is ~300 seconds. That constraint shapes everything else.

---

## Part 2 — The decisions, and how to make them yourself

### Decision 1: which precision (quantization)

Model weights are numbers. Storing them with fewer bits per number makes the
model smaller and faster, at some cost in quality.

```
  weights in GB  ~=  billions of parameters  x  bytes per parameter

  BF16   2 bytes   27B x 2   = 54 GB
  FP8    1 byte    27B x 1   = 27 GB
  INT4   0.5 bytes 27B x 0.5 = 14 GB
```

**The method:** before quantizing anything yourself, check whether the publisher
already did it. Qwen publishes an official FP8 build. That removed a whole phase
of work and every risk attached to it.

**The trap I nearly walked into:** the smallest format is not the cheapest. NVFP4
would have been ~11 GB — but it needs Blackwell GPUs, which are the most
expensive ones rentable. Minimising VRAM is not the goal; minimising cost per
useful hour is.

**When you would quantize yourself:** no official build exists, or you need a
size between the published options. Expect to spend real time validating it —
some architectures have layers that break under quantization.

### Decision 2: which GPU — the sizing method

This is where I got it wrong, so learn the full version.

```
  GPU memory needed =  weights
                    +  KV cache
                    +  activations & CUDA graphs  (~2-4 GB)
```

**Weights** you can compute from the formula above. Ours measured 28.9 GiB
against a 27 GB prediction — close enough.

**KV cache** is memory for the conversation so far. Per token:

```
  bytes/token = layers x kv_heads x head_dim x 2 (K and V) x bytes_per_value
```

For our model: 16 attention layers x 4 kv_heads x 256 head_dim x 2 x 1 byte
(FP8 cache) = **32 KB per token**. At 32K context that is 1 GiB per
conversation. I concluded 9 GiB of headroom was plenty.

**It wasn't, and here is the lesson.** vLLM does not allocate per token — it
allocates in *blocks*. Our model is a hybrid architecture where most layers use
linear attention with a large fixed state, and vLLM must make the attention
block size match that state's page size. It logged:

```
  Setting attention block size to 1568 tokens to ensure that attention
  page size is >= mamba page size.
```

1568 tokens per block instead of the usual 16. The **minimum** KV allocation
became 12.25 GiB. Real requirement: ~42.4 GiB. The 40 GB card I had chosen died
with CUDA out-of-memory.

> **The generalisable rule:** size from the *minimum allocation the engine
> actually makes*, not from per-token arithmetic. The fastest way to learn it is
> to start the server and read what it logs. One failed start costs about $0.30
> and tells you the truth.

**Then pick for bandwidth, not capacity.** Generating tokens means reading all
the weights for every token, so speed is memory bandwidth ÷ model size:

```
  A100-80GB   ~2.0 TB/s   ->  ~51 tok/s predicted, 44.5 measured
  L40S        ~864 GB/s   ->  ~22 tok/s
```

Two cards that both *fit* can differ 2x in speed. Check bandwidth, not just GB.

### Decision 3: serverless or a rented VM

```
  SERVERLESS (Modal)              VM MARKETPLACE (Shadeform, etc.)
  ==================              ================================
  scales to zero automatically    you start and stop it yourself
  billed per second alive         billed hourly while running
  $0 between requests             full rate for every idle minute
  cold start per burst            boots once, stays warm
```

**The method:** serverless wins at low duty cycle, a VM wins at high. Crossover
is roughly where duty cycle exceeds the price ratio between them. You cannot
know which side you're on until you measure — which is another reason the pilot
matters.

---

## Part 3 — Building it, step by step

### Step 1: accounts and credentials

```bash
pip install modal
modal setup                    # browser login
modal profile current          # confirms which workspace
```

Create an auth token for the endpoint:

```bash
modal workspace proxy-tokens create my-gateway
```

You get `wk-...` (an ID) and `ws-...` (a secret, **shown once**).

> **Understand who holds this.** Modal validates these at its *edge*, so the
> container never sees them. They belong wherever the *caller* runs — not in a
> Modal Secret. Getting this backwards is a common early mistake.
>
> The mirror image also holds: a Hugging Face token, if you ever need one, runs
> *inside* the container, so it does belong in a Modal Secret and does nothing
> in a local `.env`.

Put the pair in a gitignored `.env` as one combined bearer token:

```
MODAL_PROXY_TOKEN=wk-xxxx.ws-yyyy
```

Modal accepts either two custom headers or this single `Authorization: Bearer`
form. **Prefer the bearer form** — it is standard, so every OpenAI-compatible
client already speaks it, and you avoid depending on proxies to forward
non-standard headers.

### Step 2: confirm the model is actually downloadable

```bash
curl -s https://huggingface.co/api/models/Qwen/Qwen3.8-27B-FP8 | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print('gated:', d['gated'])"
```

Thirty seconds that saves you discovering a gated repo halfway through a
download.

### Step 3: download weights ONCE, separately from serving

This is the single most important structural decision in the file.

```python
@app.function(image=image, volumes=VOLUMES, timeout=3600)
def download():
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL_ID)
    hf_cache.commit()
```

Run it once: `modal run deploy.py::download`

**Why separate?** If downloading happens inside the serving path, any cache miss
re-pulls 28 GB and bills you for it — on every cold start. Separating them means
the serving path only ever reads.

### Step 4: serve with `vllm serve` as a subprocess

```python
@app.function(image=image, gpu=GPU, volumes=VOLUMES,
              scaledown_window=300, timeout=1800)
@modal.concurrent(max_inputs=32)
@modal.web_server(port=8000, startup_timeout=900, requires_proxy_auth=True)
def serve():
    subprocess.Popen(["vllm", "serve", MODEL_ID, "--host", "0.0.0.0", ...])
```

Four things worth understanding rather than copying:

**Subprocess, not the Python API.** `vllm serve` gives you a complete
OpenAI-compatible API for free. Wrapping vLLM's Python class means writing and
debugging a web layer that already exists.

**`requires_proxy_auth=True`.** Modal's own example ships an *unauthenticated*
public URL. On a small budget that means anyone who finds it can start your GPU.
With this on, unauthorized requests are rejected at the edge in ~0.5 s and
**never start a container** — junk traffic costs nothing.

**`startup_timeout=900`.** The default is 5 *seconds*. A 28 GB model needs
minutes. Leave the default and the platform kills your container while it is
starting perfectly normally.

**`scaledown_window=300`.** How long to hold the GPU after the last request.
Shorter saves idle cost but causes more cold starts. Do not go below ~2 minutes:
someone pausing 90 seconds to read an answer would trigger a cold start
mid-conversation.

### Step 5: bound the context length

Native context was 262,144 tokens. Leave it and vLLM reserves KV cache for all
of it, strangling the GPU. Set `--max-model-len 32768`. This also turns what
would be an out-of-memory crash into a clean `400` error telling the user their
prompt was too long.

### Step 6: put a gateway in front

Users should never hold the backend credential. A gateway (we used LiteLLM)
issues per-user keys, enforces rate limits, and logs every request:

```yaml
model_list:
  - model_name: qwen3.8-27b
    litellm_params:
      model: openai/Qwen/Qwen3.8-27B-FP8    # openai/ prefix + the served name
      api_base: https://<your-endpoint>/v1
      api_key: os.environ/MODAL_PROXY_TOKEN  # the wk-....ws-... bearer form
      timeout: 900                           # MUST exceed your cold start
```

The request logs are not a nice-to-have — they are how you compute duty cycle
and cost per user later. The gateway gives you your measurement infrastructure
for free.

---

## Part 4 — The five traps

Four of these reported success while being broken. That is the pattern worth
internalising.

### Trap 1: a download that succeeds and downloads nothing

The download printed `81/81 files` and exited **0**. Only ~10 MB of real bytes
landed. Hugging Face's Xet backend had filled the cache with 79-byte symlinks
pointing into a chunk store that did not survive.

Every cold start would have silently re-downloaded 28 GB.

```bash
# how to detect it
modal volume ls <volume> <path> --json    # check type: "file" vs "link"
```

Fixed with `HF_HUB_DISABLE_XET=1`.

**The second half is the better lesson.** With the fix applied, the re-run took
**0.0 seconds and changed nothing** — `snapshot_download` saw 81 filenames
present and declared the cache valid. *A cache that is wrong but complete-looking
is invisible to the tool that wrote it.* I had to delete it before correct code
could produce a correct result.

Transfer speed was the tell: 81 files in 90 s meant nothing was moving. Six
minutes meant it was. **Faster was the symptom, not the win.**

### Trap 2: sizing memory from the wrong arithmetic

Covered above. Per-token KV maths gave 9 GiB of headroom; the engine's minimum
block allocation needed 12.25 GiB. Read what the engine logs at startup.

### Trap 3: a model that answers with nothing

The endpoint worked. Short questions returned good answers. Then:

```
  "Write a detailed 400-word explanation..."  max_tokens=800
  -> 800 reasoning tokens, 0 visible tokens, content: None
```

The model ships with `xhigh` reasoning effort. It spent the entire budget
thinking and never began answering. Every user asking a real question would have
received an empty response.

```
  --default-chat-template-kwargs '{"enable_thinking": false}'
```

Two things this teaches. **Test with realistic requests** — our smoke test was
"reply with one short sentence", which passed while the deployment was unusable.
And **keep `--reasoning-parser`** even after disabling thinking: it is what made
the failure appear as empty `content` rather than as rambling answers, which
would have been far harder to diagnose.

Set it on the **model server**, not the gateway: `chat_template_kwargs` is a vLLM
extension, not part of the OpenAI spec, so routing it through a proxy means
trusting that proxy to forward a non-standard field.

### Trap 4: the gateway that drains your budget while nobody uses it

LiteLLM polls every configured model every 300 seconds by default. Our idle
window was also 300 seconds.

```
  T+0:00  health check  -> container wakes
  T+0:05  health check  -> idle timer resets
          ... forever

  24/7 GPU = ~$60/day, with zero user requests
```

Shortening the idle window makes it worse — each cycle then pays a fresh cold
start.

Three settings are needed, because one is known to be insufficient:
`background_health_checks: false`, `health_check_skip_disabled_background_models:
true`, and per-model `disable_background_health_check: true`.

**Then verify from the bill, not the config.** Leave it idle overnight and check
that the cost is zero. And do *not* stop the app to be safe — that makes the
check pass automatically while hiding exactly the defect it exists to catch.

### Trap 5: optimising the wrong thing (and how to decide)

Cold starts were ~300 s and were essentially the only cost in the deployment. GPU
memory snapshots promised to eliminate the 221 s of engine initialisation.

I measured five cold starts with snapshots enabled:

```
  743 s, 580 s, 41 s, 784 s, 522 s     median 580 s
  vs 319 s without them
```

One restore genuinely worked. The rest re-created the snapshot, costing more than
a plain cold start. Modal's published 10x figure is from a 3B model; at 28.9 GiB
it does not stabilise. **Reverted.** Cost: ~$3.90.

The decision turned on **variance, not the average**: a 784 s worst case is 13
minutes against a predictable 5. Unpredictable is worse than slow.

Three lessons, and the last is the real one:

- **Measure the cheap thing first.** One more baseline cold start ($0.35) told me
  compilation had fallen to 1.44 s, so the trend was finished and 319 s was the
  floor. That framed the whole decision.
- **Changing the image invalidates the cache that made your baseline fast.** My
  first post-revert cold start was 447 s because compilation jumped 1.44 s →
  16.60 s. It recovered. Measurements taken right after an image change are not
  comparable to earlier ones.
- **I concluded twice before the evidence was in, in opposite directions.** After
  runs 1-2 I declared it a failure — when the docs had already said snapshots
  need up to five starts. After run 3's 41 s I reported it as promising — one
  good measurement surrounded by bad ones. Both were premature.

---

## Part 5 — The verification discipline

This is the part I would most want you to take away.

**Exit code 0 is not evidence.** Every one of those traps returned success.
Structure each step so that finishing produces an *observable artifact* you can
check independently:

| Claim | Weak check | Real check |
|---|---|---|
| Weights downloaded | exit code 0 | `modal volume ls` shows 28 GiB of type `file` |
| Auth works | config has the flag | request without credentials returns 401, **zero containers started** |
| Polling suppressed | three settings present | overnight bill reads zero |
| Model works | short prompt answers | a realistic 400-word request returns non-empty `content` |
| Scales to zero | idle window configured | `modal container list` is empty after the window |

Notice the pattern: the real check is always something *outside* the thing being
tested — the volume listing, the invoice, the container list.

**A note on your own test harness.** One HTTP 500 during this project turned out
to be my readiness poll firing every 3 s for 447 s, queueing ~150 requests
against a concurrency limit of 32. Polling hard during a cold start is itself a
load pattern. Poll gently and pause after readiness.

---

## Part 6 — The economics

### What things actually cost

```
  A100-80GB GPU                  $2.50/hr
  + 4 CPU cores, 32 GiB RAM      $0.44/hr   (billed SEPARATELY -- easy to miss)
  --------------------------------------
  effective                      ~$2.94/hr

  Volume storage                 free under 1 TiB
  Rejected auth requests         $0.00
  The 28 GB download             $0.03
```

Out of $6.19 spent, **cold starts were essentially all of it.** The download was
three cents and every authentication test was free.

### The only formula that matters

```
  monthly cost = effective $/hr  x  GPU-hours actually used

  full 9x5 window  =  195 hr/month  =  ~$570
  at 30% duty      =   59 hr/month  =  ~$170
```

That 3x range is the entire reason to run a pilot. Nothing in the code predicts
it; only real usage does.

### The comparison to make honestly

Self-hosting this costs roughly $170-570/month. The same model through a hosted
API at internal-company volume is likely $10-40/month.

**Self-hosting is not the cheap option.** It is the option where your prompts
never leave infrastructure you control. That is a real and often decisive reason
— but present it as what it is, priced honestly, rather than letting someone
discover the gap in month two.

---

## Part 7 — If you were starting fresh tomorrow

The order I would use, knowing what I know now:

1. **Check for an official quantized checkpoint.** Do not quantize until you have
   confirmed nobody already did.
2. **Start the server once on a generously large GPU** and read the startup logs.
   They tell you the real memory requirement in about five minutes, for ~$0.50.
   Size down from there instead of guessing up.
3. **Download weights as a separate one-time step**, then verify the bytes landed
   with a volume listing.
4. **Turn auth on before the first deploy**, not after.
5. **Test with a realistic request immediately** — a long, substantive one. Short
   prompts hide whole classes of failure.
6. **Wire the gateway early**, because its logs are your measurement
   infrastructure.
7. **Measure the boring baseline** before optimising anything: cold start, TTFT,
   tokens per second.
8. **Only then** consider optimisation, and set a decision rule in advance for
   when you would abandon it.

And throughout: after each step, ask *"what would I look at to prove this is
actually true?"* — then look at it. Every expensive surprise in this project was
something that had reported success.
