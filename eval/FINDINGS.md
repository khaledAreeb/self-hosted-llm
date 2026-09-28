# Findings — Qwen3.8-27B capability evaluation

Run on 2026-09-28 against the live deployment (A100-80GB, 250K context, BF16
KV cache, MTP speculative decoding). The exact config is in
`eval/results/2026-09-28/deploy.py`. 24 tasks, each run twice: at the server
default (`reasoning_effort: low`) and at `medium` with 4× the token budget.
Every claim below names the result file it comes from, in
`eval/results/2026-09-28/`.

**Read this first: the tasks are synthetic** (operator decision, see
`eval/tasks.md`). They are shaped like a distribution company's work, with
answers known exactly, so grading is objective. They show what the model can do
on *this kind* of work. They are not evidence about the company's own documents.

## Verdict

| Area | `low` (default) | `medium` | In one line |
|---|---|---|---|
| Coding | 6/6 | 6/6 | Strong. Every automated test passed, including the traps. |
| Long documents | 5/6, 1 partial | **6/6** | The strongest result. 250K context works in practice, not just on paper. |
| Vision | 5/6, 1 partial | 5/6, 1 partial | Reading is reliable (12/12). Reasoning on top of what it reads occasionally slips. |
| Report writing | 2/6, 4 partial | 3/6, 3 partial | Facts reproduced accurately, but it embellishes and misses framing: invented weekdays, causes, context. |
| **Total** | **18 pass, 6 partial, 0 fail** | **20 pass, 4 partial, 0 fail** | |

No task failed outright or returned an empty answer. Every shortfall was one
wrong detail inside an otherwise correct answer, which is exactly the kind a
reader does not notice.

## Scorecard

Pass means every "good answer" criterion was met. Partial means the core was
right but a stated criterion was missed. Automated checks (`eval/grade_code.py`)
cover the five code tasks and the invoice extraction.

| Task | `low` | `medium` | Deciding detail |
|---|---|---|---|
| code-sku-parse | Pass (auto) | Pass (auto) | Used `[0-9]`, not `\d`, so Arabic-Indic digits were rejected |
| code-abc-classify | Pass (auto) | Pass (auto) | Tie-break and boundary rules exact |
| code-business-days | Pass (auto) | Pass (auto) | Found all 3 bugs: end-inclusive, Sat/Sun vs Fri/Sat, holidays ignored |
| code-sql-top-customers | Pass (auto) | Pass (auto) | Cancelled orders, date boundaries and `COUNT(DISTINCT)` all handled |
| code-review | Pass (6 of 7) | Pass (7 of 7) | SQL injection ranked first both times |
| code-reconcile | Pass (auto) | Pass (auto) | missing/short/over/unexpected edge cases exact |
| report-incident | **Partial** | **Partial** | Every time and figure exact, cause correctly "suspected". `low` never names the office-only alarm as a contributing cause; `medium` does, but drops the SMS fix from next steps |
| report-kpi-update | **Partial** | **Partial** | Causes asserted as fact; invented context ("ahead of full ramp-up", "SKU mix still stabilising") |
| report-customer-reply | **Partial** | **Partial** | Invented a weekday: "Friday, 20 September", then "Thursday" (2025: a Saturday) |
| report-meeting-actions | Pass | Pass | 5/5 actions; caught the owner change from Hany to Dina |
| report-business-case | **Partial** | Pass | Core −40,900/month right at both; `low` added two wrong break-even thresholds |
| report-rewrite-tone | Pass | Pass | All three demands kept, insults removed |
| longdoc-q3-late | **Partial** | Pass | `low` ran out of budget mid-answer; `medium` got all 10 supplier counts exact |
| longdoc-rejections | Pass | Pass | 4/4, including the one on the last lines of the document |
| longdoc-termination | Pass | Pass | 60 days: found the amendment overriding clause 19.3 |
| longdoc-payment-conflict | Pass | Pass | 8.2 vs D.4, and cited clause 1.4 for precedence |
| longdoc-audit-manager | Pass | Pass | 3 hops across 195K tokens: W6, now Nadia Soliman, 15 April |
| longdoc-all-audit-failures | Pass | Pass | 5/5, none invented |
| vision-invoice-extract | Pass (auto) | Pass (auto) | Exact JSON from a noisy, rotated scan |
| vision-invoice-audit | **Partial** | Pass | `low` found the wrong line, then computed 23,080 − 100 = 23,000 |
| vision-delivery-check | Pass | Pass | All 4 discrepancies, including the handwritten remark |
| vision-chart-read | Pass | Pass | Unlabelled bars read exactly (78, 88, 86, 87) from gridlines |
| vision-terminal-debug | Pass | Pass | Spotted `qty_onhand` vs `qty_on_hand` in the screenshot |
| vision-label-read | Pass | **Partial** | Read perfectly both times; `medium` then said "two more pieces" for 2 of 3 |

## Long context: useful in practice, with a speed cost

This is one of the two reasons the deployment exists, and it holds up.
**Twelve of twelve long-document answers were correct** once the answer budget
was large enough. These were not single-needle lookups:

- **Three hops across 195,259 tokens.** The answer needed a fact at 76% of the way in, a manager at 0.2%, and a staffing change on the last lines (`longdoc-audit-manager.md`, `@medium.md`). Both efforts got the *current* manager, not the stale one.
- **An amendment at the end overriding a clause in the middle** of a 75K-token agreement (`longdoc-termination.md`).
- **Exact counting across ~700 lines** of a 137K-token register. At `medium` every one of the ten supplier counts was right, and so was an unrequested month-by-month breakdown, checked against the data (`longdoc-q3-late@medium.md`).

The cost is time:

| Document | First read | Follow-up question (cached) | Answer speed |
|---|---|---|---|
| Short prompt | ~1 s | — | 110–135 tok/s |
| 75K tokens | 33 s | 2.4 s | 36–41 tok/s |
| 137K tokens | 71 s | 3.4 s | 29 tok/s |
| 195K tokens | 118 s | 3.6 s | 21 tok/s |

Three practical consequences:

1. **Ask several questions about the same document.** The first read is the expensive part. The prefix cache makes later questions about 30× faster to start.
2. **Long answers about long documents are slow.** At 195K tokens, generation runs 5–6× slower than on short prompts, so a 1,000-word answer takes minutes.
3. **Changing `reasoning_effort` throws away the cache.** The setting alters the start of the prompt template, so the `medium` pass re-read every document from scratch (70.8 s and 118.2 s again).

**Budget matters more than effort for hard document questions.** The counting
task used 5,928 tokens of thinking at `low` and was cut off at the 6,000 limit.
At `medium` it used 8,485 and finished (`longdoc-q3-late.md` vs `@medium.md`).
`low` does not mean "thinks briefly" when a task is genuinely hard. Clients
doing long-document work should send `max_tokens` of 10,000 or more.

Caveat: the documents are generated, so they are more repetitive than real
prose. Real contracts and manuals could be harder (less regular) or easier
(more distinctive wording). Only a run on real documents settles that.

## Vision: reads reliably, reasons on top less reliably

This is the other reason the deployment exists, and the only model in the fleet
that accepts images.

**Reading was correct in all 12 image runs.** That covered an invoice extracted
to exact JSON from a noisy, rotated scan; a handwritten remark on a delivery
note; bar heights with no value labels; small monospace text in a terminal
screenshot; and a shipping label rotated 90°.

**Reasoning on top of the reading slipped twice**, once at each effort:

- `vision-invoice-audit.md` (`low`): found the wrong line (48 × 37.50 is 1,800, not 1,900), then subtracted wrongly and reported a "correct" total of 26,220.00 instead of 26,197.20. `medium` got it right.
- `vision-label-read@medium.md`: read "Pieces: 2 of 3" and concluded "two more pieces are expected". `low` got it right.

**Enough to rely on?** For extracting what is on a page, yes. For conclusions
drawn from it, such as totals, reconciliations or "is this complete", treat the
output as a draft that a person checks. That is the same standard as for a new
clerk.

**One formatting trap:** in prose answers about images, the model writes codes
with a non-breaking hyphen (U+2011): `HH7‑2025‑0921‑44817`, `LD‑1013`. They look
identical, but pasted into a WMS search or spreadsheet lookup they will not
match. JSON output used plain hyphens (the extraction check does exact string
matching and passed). **Ask for JSON whenever the output goes into another
system**, or have the gateway replace U+2011 with `-`.

## Report writing: accurate on facts, invents around them

Every figure and time given in a prompt was reproduced correctly, across all 12
report runs. The failures were things the model **added**:

- **Weekdays that were never given.** "Friday, 20 September" at `low` and "Thursday, 20 September" at `medium`, in a customer email. 20 September 2025 is a Saturday. Different wrong answers at the two efforts show it is guessing (`report-customer-reply.md`, `@medium.md`).
- **Context presented as fact.** Contributing factors became "drivers". At `medium` it invented "Nile Mart's SKU mix is still stabilising" outright (`report-kpi-update@medium.md`).
- **Unrequested analysis with errors.** The business case's core calculation was exact, but an extra "when to revisit" section gave break-even thresholds of ~123,000 and ~231,250, where the correct figures are 142,800 and 193,125 (`report-business-case.md`).
- **Small invented deadlines** ("by close of business Friday") in the supplier email, at both efforts. Harmless here, but the same habit.
- **Structure that drops a point.** Both incident reports got every fact right but each left one expected point out: the alarm routing as a *cause* at `low`, the SMS fix as a *next step* at `medium`.

`medium` fixed the analysis error but not the embellishment. **Anything a report
states that was not in the source material needs a human check before it
goes out**, dates above all.

## Coding: strong on self-contained work

All ten automated runs passed (five tasks × two efforts). The traps were built
to catch plausible-looking code: `\d` matching Arabic-Indic digits, `COUNT(*)`
inflating order counts threefold, running totals compared on the wrong side of
the boundary. None caught it. The code review found 6 of 7 planted problems at
`low` and 7 of 7 at `medium`, with SQL injection ranked first both times. The
`low` review contained one factual slip: it said a bare `except` catches
`KeyboardInterrupt` "in Py2", when it does in Python 3 too.

Not tested: multi-file changes and agentic coding. Agentic use was measured in
phase 1: 63 requests over 10–20 minutes for two sessions, too slow to be
practical at this configuration.

## `low` vs `medium`

| | `low` | `medium` |
|---|---|---|
| Result | 18 pass, 6 partial | 20 pass, 4 partial |
| Total time, 24 tasks | 754 s | 915 s (+21%) |
| Reasoning tokens | 21,571 | 30,748 (+43%) |
| Fixed by `medium` | | invoice arithmetic, business-case thresholds, Q3 truncation |
| Broken by `medium` | | label conclusion |
| Unchanged | | invented weekdays, invented KPI context, incident framing (different miss) |

`medium` is better, and cheaper than feared: 21% more time, not the 88%
reasoning share measured earlier on one writing prompt. **Keep `low` as the
server default anyway.** Callers with ordinary `max_tokens` budgets were the
reason `medium` was dropped: it returned empty answers at 1,200 tokens. Use
`medium` for number-heavy checking and long-document counting. The simplest way
to offer both is two model names in LiteLLM pointing at the same endpoint, one
of them passing `chat_template_kwargs: {"reasoning_effort": "medium"}`. That is
untested here, so confirm it with one request before telling the team.

## Failures and reproducibility

Each of the 10 imperfect answers was re-run at the setting where it fell
short (`*@repeat*.md`). **All 10 came back byte-for-byte identical**: same
text, same token count. At temperature 0, one request at a time, this
deployment is deterministic. None of the failures is random noise.

Determinism does not show how *robust* a failure is, though. A reworded prompt
could give a different answer. The stronger evidence is which failures
appeared at **both** efforts, where different reasoning paths arrived at the
same kind of error:

| Failure | `low` | `medium` | Reading |
|---|---|---|---|
| Invented weekday in customer email | yes | yes (different day) | **Systematic.** Check every date a report states |
| Invented context in KPI update | yes | yes | **Systematic.** Check any cause or context not in the source |
| Incident report drops one expected point | yes | yes (different point) | **Systematic.** Give it the section contents, not just headings |
| Arithmetic slip when correcting invoice | yes | no | Setting-specific; `medium` fixes it |
| Wrong break-even thresholds | yes | no | Setting-specific; `medium` fixes it |
| Long-document count cut off | yes | no | Budget, not capability. Allow ≥10K `max_tokens` |
| Wrong "is it complete" conclusion on label | no | yes | Setting-specific; `low` gets it right |

Not tested: whether answers stay identical when requests run concurrently.
Batching several requests together can change results slightly.

## Compared with the hosted models

**Not done.** Task 6.4 asks for a comparison with the OpenRouter models already
in use. That needs the LiteLLM gateway running with those models on a key, and
this session has neither. The runner supports it without code changes:

    EVAL_URL=http://localhost:4000/v1/chat/completions EVAL_KEY=<litellm key> \
    EVAL_MODEL=<hosted model name> python3 eval/run_eval.py --tag <model>

The cheapest comparison that would still decide something: the five partials
above, plus the six vision tasks, since vision is the capability the hosted
models were said not to cover.

## Latency and cost per task (`low`)

From `summary.json`. The long-document and vision rows are kept separate
because their cost profile differs sharply from short prompts.

| Area | Tasks | Typical first token | Typical total | Total for 6 |
|---|---|---|---|---|
| Coding | 6 | 0.8–4.6 s | 5–18 s | 64 s |
| Report | 6 | 0.8–1.0 s | 6–22 s | 68 s |
| Vision | 6 | 1.4–3.0 s | 5–14 s | 53 s |
| Long document | 6 | 33–118 s first read, ~3 s cached | 23–275 s | 569 s |

At ~$2.94/hr (GPU plus CPU and memory), a short task costs under a cent of GPU
time and a first read of a 195K-token document about $0.12. Per-request cost is
not what drives the bill. What does is cold starts (313 s this run, 400–740 s
earlier) and the 10-minute idle window after every burst.

## Configuration as evaluated

Every flag in `deploy.py` has a comment explaining why it is set that way. The
ones someone optimising for throughput must revisit:

- **`KV_CACHE_DTYPE = "bfloat16"`**: chosen for fidelity at 250K, and it halves full-length concurrency (~5.6 → ~2.8 sequences). Switch to `fp8` for multi-user serving, then re-run `longdoc-*` to see whether long-document accuracy holds.
- **`SPECULATIVE_CONFIG` (MTP)**: 2.29× decode on short prompts; costs ~16% on cold long-prompt prefill.
- **`CHAT_TEMPLATE_KWARGS` (`low`)**: see above.
- **`MAX_CONCURRENT_REQUESTS = 32` with no `max_containers`**: a burst beyond 32 in-flight requests starts a second A100. On a fixed budget, consider `max_containers=1`.
- **`IDLE_WINDOW_SECONDS = 10 * 60`**: raised from 5 on 2026-09-27; the comment and README had not been updated and now are.

## Spend

Phase ceiling: **$12**, from a starting balance of $16.15.

| Reading | Balance | Spent this phase | Source |
|---|---|---|---|
| Phase start, 2026-09-27 | $16.15 | — | Modal dashboard |
| Before group 3 (config tests) | $13.39 | $2.76 | Modal dashboard |
| Before this evaluation run | $11.20 | $4.95 | Modal dashboard |
| Mid-run, 14:26 | $10.24 | $5.91 | Modal dashboard |
| **After the run** | **pending** | — | *to be read from the dashboard* |

Estimate until the final reading: the GPU was up from 14:09 to about 15:01
(two passes, the repeats, then the 10-minute idle window), roughly 52 minutes
at ~$2.94/hr, about $2.55. That puts the final balance near **$8.65** and phase
spend near **$7.50**, inside the ceiling. This is an estimate, not a
measurement; the dashboard figure replaces it.

## Re-running

    python3 eval/make_data.py      # same documents and images (fixed seeds)
    set -a; . ./.env; set +a
    python3 eval/run_eval.py
    python3 eval/run_eval.py --effort medium --max-tokens-scale 4
    python3 eval/grade_code.py

Results land in `eval/results/<date>/`, next to this run's, for a direct
comparison. The document token counts in `eval/tasks.md` (75,099 / 136,649 /
195,259) double as a fingerprint: if a regenerated document counts differently,
the data changed.
