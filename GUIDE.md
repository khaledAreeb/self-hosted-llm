# How to deploy an LLM on serverless GPU — what I learned doing it

A walkthrough of deploying Qwen3.8-27B on Modal, written so you can do the next
one yourself. It covers the *method* for each decision, not just the answer we
landed on, because the answers change with the model and the answers are the
easy part.

Five things went wrong along the way. Four of them reported success while being
broken. Those sections matter more than the happy path.

Parts 1-7 cover getting it running (phase 1). Parts 8-10 cover judging it
(phase 2): **how to measure speed yourself** (Part 9) and **how to know whether
the model's answers are correct** (Part 10).

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

---

# Phase 2 — Judging the model, not just running it

Phase 1 got the model serving. Phase 2 asked a harder question: **is it any
good at our kind of work, at full context?** The parts below cover how I
measured speed, and how I decided whether answers were correct. Those are the two
skills you need to evaluate any model yourself.

## Part 8 — What phase 2 did, in order

Each step had to pass before the next one was worth paying for:

| # | Step | How I knew it worked | Result |
|---|---|---|---|
| 1 | Raise context 128K → 250K with a BF16 KV cache | The startup log reports the KV-cache size and the server reaches "ready" | Fits: ~42 GiB pool, ~2.8 full-length requests at once |
| 2 | Check long context really works | Planted three codes in a 142K-token document and asked for them | All three found |
| 3 | Check whether prefix caching is on | Sent the same long document twice | 81.4 s, then 8.7 s: already on by default |
| 4 | Measure speed without MTP | `eval/decode_bench.py`, 3 runs | 49.3 tok/s |
| 5 | Turn MTP on, measure again | Same script, same prompt | 112.7 tok/s: **2.29× faster**, kept |
| 6 | Fix empty answers under `medium` thinking | Counted reasoning vs visible tokens | Switched to `low`: answers came back |
| 7 | Build a 24-task exam | Every correct answer written down first | `eval/tasks.md` |
| 8 | Run it twice (`low`, then `medium`) | Automated checks plus grading against the written answers | 18/24 and 20/24 fully correct, 0 outright failures |
| 9 | Re-run every imperfect answer | Compared word for word | All 10 identical: the failures are real |
| 10 | Send tasks through LiteLLM | Compared with the direct answers | Identical, and tool calling works |

Total cost of phase 2: **$7.49** of a $12 ceiling. The full results are in
`eval/FINDINGS.md`.

---

## Part 9 — How to measure speed yourself

### The three numbers that describe speed

Every request goes through the same stages. Each speed number measures one of
them:

```
  you send                                                        done
    |                                                               |
    v                                                               v
    |--(cold start)--|--prefill--|--decode: one token at a time------|
                     reads prompt ^                                  ^
                                  first token arrives                last token
                                  = TTFT

  COLD START   container was asleep: load the model     300-740 s
  TTFT         time to first token: mostly reading      ~1 s short prompt
               (prefilling) the prompt                   ~118 s for 195K tokens
  DECODE       tokens per second once writing starts    49 -> 113 tok/s
```

They behave differently and are fixed by different things. Cold start is fixed
by keeping containers warm. TTFT is fixed by prefix caching and prefill
settings. Decode is fixed by speculative decoding. **Always say which one you
are talking about.** "It's slow" could be any of the three.

### How the decode number is calculated

`eval/decode_bench.py` sends one request with **streaming on**, so tokens
arrive one by one and the script can time them:

```
  start = clock                      send the request
  ttft  = clock - start              when the FIRST token arrives
  total = clock - start              when the LAST token arrives
  tokens = usage.completion_tokens   the server's own count

  decode tok/s  =  (tokens - 1) / (total - ttft)
```

Two details matter:

- **Take TTFT out of the time.** TTFT is prompt-reading time, not writing time. Leaving it in makes long prompts look like slow writing. The phase 1 measurement (44.5 tok/s) mixed the two, which is one reason I re-measured.
- **Subtract 1 from the tokens.** The first token arrives *at* TTFT, not during the decode window.

The token count comes from the server itself (`stream_options:
{"include_usage": true}` makes vLLM report it at the end of the stream), not
from counting words. With thinking on, that count **includes reasoning
tokens**. That's fine for speed, since the GPU does the same work either way,
but it means you can only compare runs with the same thinking setting.

### The MTP test, step by step

This is the method. The 2.29× is just what it produced.

**1. Change exactly one thing.** The only difference between the two
deployments was the `--speculative-config` flag. For the baseline I removed it
from the command list in `serve()`, then put it back:

```python
        # Multi-token prediction; see SPECULATIVE_CONFIG above.
        "--speculative-config",
        SPECULATIVE_CONFIG,
```

Same GPU, same context length, same KV cache, same thinking setting. If two
things change, you can't tell which one caused the difference.

**2. Measure the baseline fresh, with the same code.** Phase 1 had a figure of
44.5 tok/s, but it came from a different configuration *and* a different
measuring method. Comparing against it would have made MTP look ~11% better than
it is. A new baseline cost one extra cold start plus a few minutes of runs,
under $1, which is cheap insurance against a wrong conclusion.

**3. Make sure the new setting is actually running.** `modal deploy` does not
restart a container that is already running. So each half was `modal app stop`
then `modal deploy`, then wait for a fresh container:

```bash
./venv/bin/modal app stop qwen38-27b --yes
./venv/bin/modal deploy deploy.py
# wait until this returns 200 (poll every 10 s, not faster):
curl -s -o /dev/null -w '%{http_code}' "$URL/v1/models" \
     -H "Authorization: Bearer $MODAL_PROXY_TOKEN"
```

**4. Warm up, then repeat.** The script runs once and throws the result away
(the first request after startup can be slow for unrelated reasons), then runs
three measured times. Same prompt ("Write a detailed 300-word explanation of
how warehouse cycle counting works."), `max_tokens` 1200, temperature 0. Every
run therefore produced exactly 1,200 tokens: same work, fair comparison.

```bash
set -a; . ./.env; set +a
python3 eval/decode_bench.py 3
```

**5. Compare the difference with the noise.**

```
                 run 1   run 2   run 3    mean    spread
  without MTP    49.3    49.4    49.3     49.3     0.1
  with MTP      113.3   112.2   112.7    112.7     1.1

  112.7 / 49.3 = 2.29x      difference 63 tok/s vs spread 1.1 -> ~60x the noise
```

The spread is how much results move when *nothing* changes. A difference close
to the spread means nothing. A difference 60 times the spread is real.

**6. Check the mechanism, not just the result.** A speed-up could come from
something else. vLLM logs its own speculative-decoding statistics, so I read
them to confirm MTP was doing the work:

```bash
./venv/bin/modal app logs qwen38-27b | grep "SpecDecoding metrics"
# ... Mean acceptance length: 3.18 ... Accepted: 773 tokens, Drafted: 1062 tokens
```

The small MTP head guesses 3 tokens ahead and the big model checks them in one
step. 773 of 1,062 guesses were accepted (0.68–0.73), so each step produced
about 3 tokens instead of 1. That explains the 2.29×.

**7. Look for what got worse.** Speed-ups usually cost something. vLLM warned at
startup that MTP limits how much prompt it reads per step. I timed a
142,609-token document with an empty cache: **81.4 s without MTP, 94.8 s
with it**, about 16% slower on first reads of long documents. I kept MTP because
almost every request spends most of its time writing, and repeat reads are
cached anyway. The trade is written down in `deploy.py`, not hidden.

**8. Report the strange result.** One MTP run had a 135.9 s TTFT, against about
1 s for every other run. It never happened again and I don't know why. It's
recorded in NOTES.md, not averaged away: a user who hit it would wait two
minutes on a warm server.

### Other speed facts, measured the same way

| Question | Test | Result |
|---|---|---|
| Is prefix caching on? | Same 142K document twice | 81.4 s, then 8.7 s: yes |
| Does context length slow writing? | Decode speed from the eval runs, grouped by prompt size | ~125 tok/s short, 36–41 at 75K, 29 at 137K, 21 at 195K |
| What does `medium` thinking cost? | Total time of all 24 tasks at each setting | 754 s vs 915 s: +21% |
| Does changing effort break the cache? | Same document under `low` then `medium` | Yes: full re-read (71 s again) |

### Mistakes to avoid when you measure

- **Comparing across configurations.** Measure both halves yourself, with the same script.
- **One run.** You can't see noise in a single number.
- **Trusting the first run after an image change.** Compile caches refill; the first start of a new config was 655 s, the second 403 s.
- **Polling too hard while waiting.** Polling every 3 s during a cold start once caused a server error. Every 10 s is enough.
- **Forgetting reasoning tokens.** Two runs with different thinking settings don't do the same amount of work.

---

## Part 10 — The eval folder, and how I knew the answers were right

### What it's for

Trying a few prompts tells you how the model *felt* that afternoon. An
evaluation set is a **fixed exam**: the same questions, the same correct
answers, rerunnable after any change. Swap the model, change a flag or switch
the KV cache to FP8, run it again, and you get a before/after comparison.

```
  eval/
  |
  |-- make_data.py      builds the test documents and images (same files every time)
  |       |
  |       +--> docs/    3 long documents: 75K, 137K, 195K tokens   (not in git)
  |       +--> images/  6 images: invoices, delivery note, chart,  (not in git)
  |                     terminal screenshot, shipping label
  |
  |-- tasks.md          24 questions, each with "good answer looks like"
  |       |
  |       v
  |-- run_eval.py       sends every task to the model, one at a time
  |       |
  |       +--> results/2026-09-28/
  |              <task>.md       the answer next to its expected answer
  |              summary.json    timings and token counts for every task
  |              deploy.py       the exact config that produced them
  |
  |-- checks/           small test programs for tasks with checkable output
  |-- grade_code.py     runs every check against the results
  |
  |-- FINDINGS.md       what it all means, every claim pointing at a result file
  |
  |-- decode_bench.py   (separate) the speed benchmark from Part 9
```

### How I knew an answer was correct: six layers

**1. The right answer existed before the question.** The documents were
generated, so every fact in them was planted on purpose and `make_data.py`
prints the ground truth. Example: the script forced Sinai Beverages to exactly
21 late deliveries in Q3, and made a *different* supplier (Nile Plastics, 48)
the leader for the full year. An answer of "Nile Plastics" therefore proves the
model ignored the date range. The trap is part of the design.

**2. The expected answers were written, and committed, before the model ran.**
Every task in `tasks.md` has a "Good answer looks like" section. Git shows the
order: the tasks were committed in `2961f06`, the results in `a0b9dab`, later.
Writing the answer afterwards invites grading on impression ("that sounds
right"). That's a vibe check, not an evaluation.

**3. Wherever possible, a program grades, not a person.** For six tasks the
answer is code or JSON, so `checks/` runs it:

```
  code-sql-top-customers   builds a database full of traps (a huge cancelled order,
                           orders on 2024-12-31 and 2026-01-01), runs the model's
                           query, compares with an answer computed separately in Python
  code-sku-parse           feeds 22 SKUs, including Arabic-Indic digits that
                           Python's \d wrongly accepts
  vision-invoice-extract   parses the JSON and compares every field and line item
```

**4. Check the checker.** A test that passes everything proves nothing. Before
grading the model, I fed every check two fake answers: a correct one (must
PASS) and a plausible wrong one (must FAIL). All six told them apart. For
example, the SQL check caught `COUNT(*)` inflating order counts roughly
threefold. Only then did I trust the checks on the model's answers.

**5. Grade everything else strictly against what was written.** For the 18 tasks
without a program, I read each answer against its criteria. "Partial" meant any
written criterion was missed, even if the rest was excellent. Two consequences:

- I downgraded both incident reports from Pass to Partial after noticing each missed one listed point. The rule applies to the results I like too.
- When an answer claimed more than was asked (a month-by-month breakdown of late deliveries), I checked the extra claims against the data. Extras are where the errors were.

**6. Run it again.** At temperature 0, every imperfect answer re-ran **word for
word identical**, so the failures are real, not bad luck. That determinism
also allowed an exact gateway test: the same tasks through LiteLLM produced
identical text, which shows the gateway changes nothing.

### What this method cannot tell you

- **Synthetic isn't real.** The generated documents are more repetitive than real contracts. The results show capability on this *kind* of work, not on your documents.
- **I graded the 18 manual tasks.** The criteria were fixed in advance, which limits bias, but open a few files in `eval/results/2026-09-28/` and judge them yourself. It takes ten minutes.
- **One question per skill.** Two tasks per skill would be twice as sure.
- **Temperature 0 only.** Users with other settings may get more varied answers.

### Adding your own task

Add a block to `eval/tasks.md` in the same format. The runner refuses a task
until its "good answer" is filled in, on purpose:

```
## TASK: report-my-real-task
- area: report
- max_tokens: 3000
- attach: none

### Prompt
<paste the real request, with the real material>

### Good answer looks like
<the facts it must contain, what it must NOT invent, the length limit>
```

Then run just that task and read the result file:

```bash
python3 eval/run_eval.py report-my-real-task
```

A real document from your own work, with an answer you already know, is worth
more than all 24 synthetic tasks. That is the next step this evaluation
points to.

---

# Phase 3 — How many people can use it at once

## Part 11 — Load testing, in one page

Phases 1–2 sent one request at a time. Phase 3 kept **N requests in flight at
once** and watched how the answers slowed down. The full step-by-step guide,
with every command, is **`bench/GUIDE.md`**; the results are in
`bench/FINDINGS.md`. The short version:

| Question | How it was answered | Result |
|---|---|---|
| Is the tool measuring the right thing? | Ran GuideLLM and `decode_bench.py` on the same prompt | Generation speed within 0.5% |
| Can the cheaper memory setting be trusted? | Re-ran the 6 long-document tasks on FP8 | 6/6 pass, and capacity doubles |
| How many requests at once? | 1, 4, 8, 16 and 30 in flight, real prompts | **4** within a 20 s target |
| Why does it slow down? | vLLM's own counters, every 5 s | Compute-bound up to 16; queueing at 30 |
| Does MTP still help under load? | Same test with MTP off | Yes: 42.6 s → 23.5 s at 8 |
| How many people is that? | Binomial "95% of the time" rule | ~10–20 chat users; 8 agents |

Three lessons carry over to any model:

1. **Decide what "usable" means before you look.** Otherwise you will choose the target that makes the result look good.
2. **Requests are not users.** People are busy only part of the time, and their requests cluster. Size for the bursts, not the average.
3. **Test the tool before trusting it.** GuideLLM had four rough edges in its current version. The worst was its warmup: the default setting threw away every request (all zeros), and the alternative threw away none. They were caught by running it against its own mock server first, for $0.
