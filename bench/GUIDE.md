# How to load test an LLM deployment yourself

A step-by-step guide to phase 3 of this project: measuring how many people one
A100 running Qwen3.8-27B can serve at once. It follows what was actually done,
in order, with the real numbers and the mistakes caught along the way. The
results are in `FINDINGS.md`; the commands reference is `README.md`.

Written for someone who has deployed a model and measured it one request at a
time, and now needs to know whether it survives a team.

---

## Part 1 — The ideas you need first

### Why single-request speed doesn't answer the question

Phase 2 measured 112.7 tok/s for one request on an idle GPU. That tells you
nothing about ten people, because a GPU doesn't serve people one after
another. It serves them **together**, in batches:

```
  1 request:    GPU step = [ A ]                    A gets the whole step
  8 requests:   GPU step = [ A B C D E F G H ]      each gets 1/8th of the work,
                                                    but the step itself is not 8x slower
```

Batching is why total throughput rises with load (93 tok/s at 1, 770 tok/s at
30) while each person's speed falls (100 tok/s at 1, 35 tok/s at 30). Both
numbers are true, and the load test measures the curve between them.

### Concurrent requests are not users

A person is not asking the model all the time. They read, think and type. The
share of their working time with a request in flight is their **busy
fraction**:

```
  a chat user:  |==req==|......reading and typing......|==req==|.........
                   15 s              ~1-2 min
                busy ~10-20% of the time

  a coding agent: |==req==|==req==|==req==|==req==|==req==|==req==|
                busy ~100%: each answer triggers the next request
```

So the test measures **simultaneous requests** (what the GPU sees), and turns
them into **people** at the end (Part 10).

### Which "waiting" matters

With thinking on, a request goes through four stages:

```
  sent ---> [queue] ---> [read prompt] ---> [think ...] ---> [answer ...] ---> done
                                     ^                  ^                   ^
                                  first token      first VISIBLE       last token
                                  (TTFT)           word (TTFOT)
```

**TTFT** is almost always short (~1 s). What a person actually waits for is the
**first visible word**, which comes only after thinking ends. That is the
number the "usable" target is written in.

### Why p95, not the average

**p50** (the median) is the typical experience. **p95** means 95% of requests
did at least this well, and 1 in 20 did worse. Users remember the slow ones,
so the target is on p95. You need at least ~20 samples for a p95 to mean
anything, which is why every level runs at least 20 requests.

---

## Part 2 — Plan before you spend

Four decisions were written into `openspec/changes/multi-user-load-test/design.md`
before any GPU time was bought.

**1. Define "usable" before seeing results.** If you choose the target after
seeing the curve, you will pick the one that flatters it. The targets here:

- **Interactive:** p95 first visible word ≤ 20 s, 95% of requests writing at ≥ 15 tok/s (about twice reading speed), ≤ 1% failures.
- **Agents:** p95 time per step ≤ 20 s.

**2. Test the configuration people will actually get.** The phase 2 setup (BF16
KV cache, no container limit) was built for one person judging quality.
Measuring it would answer the wrong question, so the config changed first
(Part 4).

**3. Cap the spending in advance, with gates.** Ceiling $4. Before each paid
"window" the balance was read from the dashboard, and the window ran only if
it still fit. Every paid step was grouped into as few windows as possible,
because every cold start costs about 10 minutes of GPU.

**4. Stay under the platform's own limits.** One container takes 32 requests at
once (`MAX_CONCURRENT_REQUESTS`). The top level tested is **30**, because the
counter recorder (Part 7) uses one slot too. With `max_containers=1`, a 33rd
request would queue and distort the level being measured.

---

## Part 3 — Install the tool, then test it for free

The tool is [GuideLLM](https://github.com/vllm-project/guidellm), from the vLLM
project. I chose it over writing my own because it has load profiles,
per-request timing and, most importantly, it records the **first visible
token** separately from the first token. That was checked by reading its
source, not assumed.

```bash
python3 -m venv bench/.venv                     # its own environment (git-ignored)
bench/.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
bench/.venv/bin/pip install "guidellm[recommended]==0.7.4"
python3 bench/make_datasets.py                  # real prompts from eval/tasks.md
```

CPU-only torch keeps it to ~1.6 GB; the load test never uses a local GPU.

**Then test everything against GuideLLM's mock server, before spending a
cent.** The mock imitates an OpenAI endpoint on your laptop:

```bash
bench/.venv/bin/guidellm mock-server --host 127.0.0.1 --port 8123 \
    --model Qwen/Qwen3.8-27B-FP8 --ttft-ms 200 --itl-ms 10 --output-tokens 150 &
BENCH_API_KEY=dummy MODAL_PROXY_TOKEN=unused \
    bench/run.sh interactive 4 --target http://127.0.0.1:8123 --no-sampler --label mock-interactive-4
python3 bench/summarize.py
kill %1
```

**The check that matters:** the mock was told 200 ms to first token and 10 ms
per token, so the summary must show ~0.2 s and ~96 tok/s. If your tool can't
reproduce numbers you *set*, it can't measure numbers you don't know.

### The four traps this caught, all for $0

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | Crashed: `'DatasetDict' object has no attribute 'info'` | The JSON loader returns a set of named splits | pass `"load_kwargs": {"split": "train"}` |
| 2 | Only 12 of 25 requests sent | GuideLLM stops when its dataset runs out | cycle the 12 prompts 20 times (240 records) |
| 3 | Summary table **all zeros** | Warmup defaulted to 10% of the *time cap*: 24 s of a 5 s run | … |
| 3b | …then nothing excluded at all | The request-based warmup mode did nothing in 0.7.4 | drop 10% at each end in `summarize.py`, visibly |
| 4 | "Extra inputs are not permitted" | The shared-prefix option moved to `prefix_buckets` | use the new field |

And one in the mock itself: `--processor` crashes on Qwen's tokenizer, so
leave it out.

**Trap 3 is the lesson.** The run "succeeded", exit code 0 and a results file
written, but it measured nothing. Always look inside the result: how many
requests, how many were measured, and are the numbers plausible?

Two more things `summarize.py` does itself rather than trusting the tool's
summary:
- **Generation speed** is `(tokens − 1) / (last token − first token)`, the same formula as `eval/decode_bench.py`. GuideLLM's per-request `output_tokens_per_second` includes the wait for the first token.
- **Failures** include empty answers, and they stay in the count.

---

## Part 4 — Change the config, then check you didn't break it

Two changes in `deploy.py`:

| Setting | Before | After | Why |
|---|---|---|---|
| `KV_CACHE_DTYPE` | `bfloat16` | `fp8` | Half the memory per token, so twice the room for several people's long prompts |
| `max_containers` | (none) | `1` | A burst queues on one GPU instead of silently starting a second A100 |

**FP8 had a known risk:** a benchmark showed it losing accuracy at long context,
which is why phase 2 used BF16. So the first thing done on the new container
was to re-run the six long-document tasks from phase 2 and grade them against
the same criteria:

```bash
python3 eval/run_eval.py --tag fp8 longdoc-q3-late longdoc-rejections \
    longdoc-termination longdoc-payment-conflict longdoc-audit-manager longdoc-all-audit-failures
```

**Result: 6/6 pass.** The one task that ran out of room on BF16 now finishes,
with every count exact.

**How I knew FP8 was really active:** vLLM's startup log shows `kv cache group
sizes [1600, ...]`, against `[800, ...]` in the BF16 log. The same memory now
holds twice the tokens per block.

**Speed changed in both directions:**
- short-prompt generation got slower (112.7 → 73.2 tok/s);
- long-context generation got much faster (29 → 98 tok/s at 137K);
- first reads got 12–21% slower.

Record trade-offs like these; don't average them away.

---

## Part 5 — Validate the tool against a benchmark you trust

On the warm endpoint, run the same prompt through both tools:

```bash
bench/run.sh validate 1          # GuideLLM, one at a time, decode_bench's prompt
python3 eval/decode_bench.py 3   # the phase 2 script
```

| | GuideLLM | decode_bench |
|---|---|---|
| Generation speed | 72.8 tok/s | 73.2 tok/s |
| First token | 0.6 s | 1.07 s |

**Generation agrees within 0.5%.** First token differs by 0.45 s, more than the
10% allowed, so the rule was to find the cause before trusting either tool:

```bash
curl -s -o /dev/null -w 'tls_setup=%{time_appconnect}s\n' "$URL/v1/models" -H "Authorization: Bearer $MODAL_PROXY_TOKEN"
# tls_setup=0.34s
```

`decode_bench` opens a new HTTPS connection for every request, and the TLS
handshake alone costs 0.34 s. GuideLLM reuses its connection. So the gap is
client overhead, not the server, and irrelevant against a 20 s target.
**Explained, not ignored.**

---

## Part 6 — Run the levels

**Warm the endpoint first.** A request to a sleeping endpoint starts a
container, and you would be timing a cold start. Then run each level:

```bash
for N in 1 4 8 16 30; do bench/run.sh interactive $N; done
bench/run.sh interactive 8 --label interactive-8-repeat    # same level again = noise
for N in 1 4 8; do bench/run.sh agent $N; done
```

**What one level does:** N requests always in flight, until `max(20, 3N)` are
measured (after dropping 10% at each end), or 4 minutes. `run.sh` starts the
counter recorder alongside, and passes the API key from `.env` at run time.

**The whole of window 1 took ~46 GPU-minutes and cost $2.23.** It ran in one
warm session: FP8 re-check, validation and every load level.

**At the end of a window, release the GPU at once:**

```bash
./venv/bin/modal app stop qwen38-27b --yes && ./venv/bin/modal deploy deploy.py
./venv/bin/modal container list     # should be empty
```

`stop` alone would take the endpoint offline. Stop followed by deploy releases
the GPU now, instead of paying for the 10-minute idle window, and leaves the
endpoint up.

---

## Part 7 — Read the results

```bash
python3 bench/summarize.py
```

The interactive curve from this phase:

| In flight | First visible word, typical / slowest 5% | Writing speed (typical) | Verdict |
|---|---|---|---|
| 1 | 8.8 / 16.6 s | 100 tok/s | within target |
| **4** | **10.3 / 15.5 s** | 84 tok/s | **within target** |
| 8 | 13.3 / 23.6 s | 75 tok/s | misses by 3.6 s |
| 16 | 17.3 / 30.2 s | 56 tok/s | misses |
| 30 | 25.4 / 66.8 s | 35 tok/s | misses |

**Capacity is the last level within target: 4.** Check the level next to it
too. At 8 the p95 is 23.6 s, and the repeat gave 23.5 s, so the miss is real,
not noise.

### Is a difference real? Compare it with the noise

The level at 8, run twice with nothing changed: visible p95 differed by 0.1 s,
writing speed by 2.8 tok/s, throughput by ~10%. Any "A is faster than B" claim
must beat those numbers.

### Why does it slow down? Ask the server

`metrics_sampler.py` records vLLM's own counters every 5 seconds. Read them
like this:

```
  waiting > 0 ?  ---- no ----> kv near 100% + preemptions ?  -- no --> COMPUTE-BOUND
       |                              |                               (normal: more
      yes                            yes                               requests share
       |                              |                                each GPU step)
       v                              v
    QUEUEING                     OUT OF MEMORY
  (the scheduler can't          (more KV room would help:
   start them yet)               FP8, shorter contexts)
```

What this phase showed:
- **1–16 in flight:** waiting 0, KV ≤ 29%, no preemptions. Compute-bound.
- **30 in flight:** 16 requests waiting, KV only 54%, no preemptions. Queueing, and not memory.

The next suspect is vLLM's per-step token budget (`--max-num-batched-tokens`).
It hasn't been tested yet: see Part 11.

---

## Part 8 — The two special cases

### Coding agents

Agents resend their whole context every step. The `agent` workload imitates
that: 17,000-token prompts, 16,000 of them shared, 300-token replies.

| In flight | Step time, p95 | Verdict |
|---|---|---|
| 1 | 5.7 s | within target |
| 4 | 9.2 s | within target |
| 8 | 15.0 s | within target |

The **prefix cache** is why this works. The counters show 81–85% of prompt
tokens served from cache, so a 17K prompt costs little more than a 1K one.

### One long document among users

Eight people working, and one person sends a fresh 137K-token document:

```bash
bench/run.sh interactive 8 --label interference-8 --requests 70 &
sleep 40; python3 bench/interference.py interference-8
wait
```

`interference.py` adds a unique first line so the cache can't help: this is the
worst case, a document nobody has sent before.

| Everyone else's first visible word | typical / slowest 5% |
|---|---|
| outside the document's read | 11.5 / 20.9 s |
| **during its read (~1.5 min)** | **34.0 / 100.2 s** |

**One long document makes the whole room wait.** That's the biggest practical
risk for a shared deployment, and a single-request test would never show it.

---

## Part 9 — Compare two configurations under load (MTP)

MTP gave 2.29× on one request. Under load, the GPU has less spare compute, so
the gain could shrink or reverse. The test: the same levels (8 and 30) with the
`--speculative-config` flag removed, deployed from a scratch copy so the real
`deploy.py` never changed.

| | MTP on | MTP off |
|---|---|---|
| 8 in flight, visible p95 | 23.5 s | 42.6 s |
| 8 in flight, throughput | 392–435 tok/s | 247 tok/s |
| 30 in flight, throughput | 770 tok/s | 633 tok/s |

**Decision rule, written in advance:** keep MTP if it is better at the level
nearest capacity by more than the noise. At 8 it wins by 19 s against 0.1 s of
noise, so it stays.

It also ruled out a hypothesis: 14 requests still queued at 30 without MTP, so
MTP's prompt-reading limit is not what causes the queueing.

**Why temperature 0 matters here:** both configurations generate the same
tokens for the same prompts, so the only difference is speed.

---

## Part 10 — Turn requests into people

Capacity is 4 simultaneous requests. How many people is that?

**The tempting rule:** capacity ÷ busy fraction = 4 ÷ 0.2 = 20 people. That is
too optimistic. People don't take turns; sometimes five of them ask at once.
Size so that **95% of the time** no more than 4 are asking:

```bash
python3 -c "
from math import comb
def p_over(n, p, cap): return sum(comb(n,k)*p**k*(1-p)**(n-k) for k in range(cap+1, n+1))
print(max(n for n in range(1,200) if p_over(n, 0.20, 4) <= 0.05))"
# 10
```

| Busy fraction | People (95% rule) | Average rule, for comparison |
|---|---|---|
| 10% | 20 | 40 |
| 20% | **10** | 20 |

**Past capacity nothing fails, it slows down.** A moment with 8 people asking
at once looks like the level-8 row: ~13 s typical, ~24 s slowest.

The busy fraction here is an **assumption**. The first week of a real pilot
would measure it from LiteLLM's logs, and the table above then gives the real
number.

---

## Part 11 — Do it again after any change

The obvious next experiment is the lever Parts 7 and 8 point to:

1. In `deploy.py`, add `--max-num-batched-tokens` with a larger value (e.g. `8192`) to the vLLM command, with a comment saying why.
2. Deploy, warm, and run only the levels that matter:
   ```bash
   bench/run.sh interactive 30 --label interactive-30-mnbt
   bench/run.sh interactive 8 --label interference-8-mnbt --requests 70 &
   sleep 40; python3 bench/interference.py interference-8-mnbt; wait
   ```
3. `python3 bench/summarize.py` and compare with today's rows, which stay in `results/2026-09-29/`. Did `wait` at 30 drop? Did the stall shrink? Is the difference bigger than the noise?
4. Stop and deploy at the end. Budget about $1: one cold start plus ~10 minutes.

**The checklist, for any model and any GPU:**

- [ ] Write the "usable" target and the spending ceiling down first.
- [ ] Deploy the configuration people will really get.
- [ ] Re-check quality whenever a setting could affect it (like FP8).
- [ ] Test the tool on a mock server, and look inside its output.
- [ ] Validate it against one benchmark you trust.
- [ ] Warm up, run levels from low to high, and repeat one level for noise.
- [ ] Record the server's counters, and explain every slowdown with them.
- [ ] Test the ugly cases: agents, one huge request.
- [ ] Turn requests into people with bursts in mind, and state the assumption.
- [ ] Release the GPU the moment you're done: stop, then deploy.

## What phase 3 cost

| Window | GPU time | Cost |
|---|---|---|
| Tooling, tests, docs | none (laptop + mock server) | $0 |
| Window 1: FP8 re-check, validation, all load levels | ~46 min | $2.23 (dashboard) |
| Window 2: MTP off at 8 and 30 | ~18 min | ~$0.87 (estimated) |
| **Total** | | **~$3.10**, under the $4 ceiling |
