# Findings — how many people one A100 serves

Measured 2026-09-29 on the configuration users now get: Qwen3.8-27B-FP8,
one A100-80GB, 250K context, **FP8 KV cache, MTP on, `max_containers=1`**,
thinking at `low`, temperature 0. Every number cites a file in
`bench/results/2026-09-29/` (`<label>.json` plus `<label>.metrics.csv`) or an
entry in `NOTES.md`. Method: `bench/README.md`. How to do it yourself:
`bench/GUIDE.md`.

## The answer

| Kind of use | Simultaneous requests within target | People that supports |
|---|---|---|
| **Interactive** (chat, coding, reports) | **4** (8 just misses) | **about 10–20** |
| **Coding agents** | **at least 8** (the most tested) | **about 8 agents running at once** |
| **One long document among users** | — | stalls everyone for its ~1.5-minute read |

"Within target" means the targets fixed in `design.md` **before any result
existed**:
- **Interactive:** 95% of requests show their first visible word within 20 s and write at 15 tok/s or more, with at most 1% failing.
- **Agents:** 95% of steps finish within 20 s.

## Interactive capacity curve

Real coding and report prompts (`datasets/interactive.json`), N requests
always in flight:

| In flight | First visible word, typical / slowest 5% | Writing speed, typical / slowest 5% | Whole request, typical / slowest 5% | Throughput | Verdict |
|---|---|---|---|---|---|
| 1 | 8.8 / 16.6 s | 100 / 90 tok/s | 11.3 / 19.2 s | 93 tok/s | within target (16 requests: short sample) |
| **4** | **10.3 / 15.5 s** | 84 / 77 tok/s | 14.0 / 19.0 s | 144 tok/s | **within target** |
| 8 | 13.3 / 23.6 s | 75 / 66 tok/s | 16.0 / 28.3 s | 392 tok/s | misses (p95 23.6 s; 1 empty answer) |
| 8, repeat | 12.6 / 23.5 s | 73 / 63 tok/s | 15.6 / 30.2 s | 435 tok/s | misses (p95 23.5 s) |
| 16 | 17.3 / 30.2 s | 56 / 49 tok/s | 22.5 / 37.5 s | 631 tok/s | misses |
| 30 | 25.4 / 66.8 s | 35 / 31 tok/s | 34.0 / 74.7 s | 770 tok/s | misses; requests queue |

(`interactive-{1,4,8,16,30}`, `interactive-8-repeat`.)

**Read it as a slope, not a cliff.** Nothing breaks as load rises: every
request still succeeded except one, and writing speed stays above reading
speed even at 30. Waits simply grow.

- **The 20 s target is what makes 4 the answer.** Level 8 misses it by 3.5 s at the 95th percentile, and both runs agree to 0.1 s.
- **With a 25 s target, capacity would be 8.** The raw results are kept, so a different target can be applied without re-running.

**Run-to-run noise at 8** (the same level run twice):

| Measure | Difference between the two runs |
|---|---|
| Visible p95 | 0.1 s |
| Visible p50 | 0.7 s |
| Writing speed | 2.8 tok/s (~4%) |
| Throughput | 43 tok/s (~10%) |

The one failure at 8 was not caused by load. The model thought for its whole
4,000-token budget and never started the answer. That failure mode was already
known from phase 2, and it did not recur in the repeat.

## Why it slows down: the server's own counters

| In flight | Peak running | Peak waiting | Peak KV use | Preemptions |
|---|---|---|---|---|
| 1–16 | = N | **0** | 2–29% | 0 |
| 30 | 30 | **16** | 54% | 0 |

- **Up to 16: compute-bound.** Nothing waits and memory is barely used. The GPU gives each request a smaller share of every step, so everyone slows together. That is the normal shape; more memory would not help.
- **At 30: requests queue inside vLLM,** yet KV use is only 54% with no preemptions, so memory is not the cause.
  - It is **not MTP** either: 14 were still waiting with MTP off (`interactive-30-nomtp`).
  - The cause is not established. The next suspect is vLLM's per-step token budget (`--max-num-batched-tokens`), which new requests' prompt reading has to share with everyone's generation. That is the operator's next tuning lever.
- **FP8 was not needed for this workload,** but its headroom is real: 54% at the heaviest load. With BF16 the same load would have filled about 100%.

## Coding agents

Synthetic agent steps: a 17,000-token prompt, 16,000 tokens of it shared,
the way an agent resends its context; 300-token replies.

| In flight | Step time, typical / slowest 5% | Verdict |
|---|---|---|
| 1 | 5.5 / 5.7 s | within target |
| 4 | 8.8 / 9.2 s | within target |
| 8 | 13.6 / 15.0 s | within target |

(`agent-{1,4,8}`.)

- **The prefix cache served 81–85% of prompt tokens,** close to the 94% that is shared (read from the `prefix_*` counters). That is why 17K-token prompts are cheap here.
- **Requests queued at 4 and 8** (peak waiting 3 and 5), still within target.
- **Not measured:** real agent sessions chain dozens of steps. At 8 agents, a 60-step task at ~14 s a step takes about 14 minutes.

## One long document among users

Eight interactive users running. One fresh 137K-token document, with a
unique first line so the cache could not serve it, sent mid-run
(`interference-8`, `interference-8.overlap.json`):

| Interactive requests | First visible word, typical / slowest 5% | Whole request, slowest 5% |
|---|---|---|
| Outside the document's read (43) | 11.5 / 20.9 s | 26.7 s |
| **During its read (13)** | **34.0 / 100.2 s** | **113.4 s** |

**The document itself** took 86 s to start and 95 s in total, and was answered
correctly: all 4 rejections found.

So **one person reading a long document makes everyone else wait**, for as
long as the read takes. The likely mechanism is that its prompt reading takes
most of each step's token budget, which is the same lever as above. This is
the biggest practical risk for a shared deployment.

## MTP under load: kept

Same FP8 config, with and without `--speculative-config`, same prompts,
temperature 0 (`interactive-{8,30}-nomtp`):

| | MTP on | MTP off |
|---|---|---|
| **8 in flight**, visible p95 | 23.5–23.6 s | **42.6 s** |
| 8 in flight, writing speed | 72–75 tok/s | 40 tok/s |
| 8 in flight, throughput | 392–435 tok/s | 247 tok/s |
| **30 in flight**, writing speed | 35 tok/s | 29 tok/s |
| 30 in flight, throughput | 770 tok/s | 633 tok/s |
| 30 in flight, visible p95 | 66.8 s | 61.9 s |

The rule in `design.md` was to keep MTP if it is at least as good at the level
nearest capacity by more than the noise. **At 8 it wins by 19 s at p95,
against 0.1 s of noise.** Level 4 was not re-run without MTP; 8 is the nearest
level tested both ways.

The gain shrinks as the GPU fills: at 30 the p95 is a tie and writing is +21%.
It never reverses.

## FP8 KV cache: kept

- **Accuracy:** 6/6 long-document tasks pass on FP8 (`eval/results/2026-09-29/*@fp8.md`). The one that ran out of room on BF16 now finishes with exact counts.
- **Capacity:** doubled; the KV block went from 800 to 1,600 tokens.
- **Single-request speed trade** (`NOTES.md`, "FP8 KV cache"):
  - short-prompt generation 112.7 → 73.2 tok/s;
  - 137K-context generation 29 → 98 tok/s;
  - first reads 12–21% slower.

## From requests to people

A person is not always asking: they read, think and type. "Busy fraction" is
the share of their working time with a request in flight.

- **Assumed**, not measured: interactive users **10–20%** (one ~15 s request every 1–2.5 minutes of active use); agent users **100%** while their agent runs.
- **Sizing rule:** the number of people for whom **95% of the time** no more than the capacity are asking at once (binomial model). Dividing capacity by the busy fraction would be too optimistic, because people's requests cluster.

| Capacity | Busy fraction | People (95% rule) | People (average rule, optimistic) |
|---|---|---|---|
| **4** (20 s target) | 10% | **20** | 40 |
| **4** | 20% | **10** | 20 |
| 8 (25 s target) | 10% | 48 | 80 |
| 8 | 20% | 25 | 40 |

**Example, a mixed team:** 1 coding agent takes one slot all the time,
leaving 3. Seven people chatting at 20% need at most 3 at once, 95% of the
time, so **7 chatters plus 1 agent fit**. Ten chatters alone already burst to
4, so ten chatters plus an agent would run over. Past capacity, answers don't
fail; they slow down along the curve above.

**What the 95% rule means in practice:** at 20 chat users at 10%, about 1
moment in 25 has more than 4 people asking. In those moments the slowest
first-visible-word wait goes from about 15 s toward the 24 s seen at 8.

## What this does not tell you

- **Real traffic.** 12 real prompts cycled at temperature 0; closed loop (N always busy), a worst case. The busy fraction is an assumption; LiteLLM's logs during a real pilot would measure it.
- **Images under load.** Not tested; an image request is a ~1–2K-token prompt and should behave like a short text request.
- **`medium` thinking.** It uses ~43% more reasoning tokens (phase 2), so expect capacity somewhat below these figures.
- **Why requests queue at 30, and the long-document stall.** Both point at the per-step token budget. That is untested.

## Recommendations

1. **Pilot with about 10 people,** not 30. That is where the measurements say answers stay under ~15–20 s to the first word.
2. **Warn users about long documents.** One 137K-token read makes everyone else wait about a minute and a half. Next test: raise `--max-num-batched-tokens` and re-run `interference-8` and `interactive-30` (~$1).
3. **Keep FP8, MTP and `max_containers=1`.** Each was measured, not assumed.
4. **Measure the real busy fraction** from LiteLLM logs in the pilot's first week, then read the user count off the table above.
5. **30 users need more than one A100,** or a much looser latency target. `max_containers` is where to raise that deliberately, with a budget.

## Cost of this phase

| | Balance | Spent |
|---|---|---|
| Phase 3 start | $7.85 | — |
| After window 1 (FP8 re-check, validation, load runs) | $5.62 | $2.23 |
| After window 2 (MTP off; ~18 GPU-minutes) | ~$4.75, *estimated* | ~$3.10 |

The ceiling was $4. The final figure is to be confirmed from the dashboard
(task 6.3).
