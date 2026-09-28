# Evaluation set — Qwen3.8-27B capability

24 tasks across coding, report writing, long-document reasoning and vision.

**Synthetic, by operator decision (2026-09-28).** The company, people and
documents are fictional ("Harbor & Hale Distribution"), shaped like the work a
distribution business does. Each task hides facts whose correct answer is known
exactly, so grading is objective rather than a matter of impression. The cost:
results show what the model can do on this *kind* of work, not how it handles
the company's own documents. A later run on real material would close that gap.

**Agentic coding is deliberately excluded.** It was already measured in phase 1:
two OpenCode sessions produced 63 requests over 10-20 minutes, because agents
turn one question into dozens of sequential calls. Re-testing would spend budget
confirming a known answer.

## How to run

    python3 eval/make_data.py            # documents + images (deterministic)
    set -a; . ./.env; set +a
    python3 eval/run_eval.py             # all tasks, one at a time
    python3 eval/grade_code.py           # automated checks where they exist

Automated checks (`eval/checks/`) exist for the five coding tasks that produce
runnable code and for invoice extraction. Every other task is judged by reading
the answer against its "Good answer looks like", which was written before any
model output existed.

## Format

Each task is a `## TASK:` heading followed by these fields and two sections:

    ## TASK: <unique-id>
    - area: coding | report | long-document | vision
    - max_tokens: <number>
    - attach: <path to a document or image, or "none">

    ### Prompt
    <exactly what gets sent to the model>

    ### Good answer looks like
    <written BEFORE running -- what would make you trust the answer?>

For long-document tasks the document is sent first and the prompt after it.
For vision tasks the image is sent with the prompt. Inside a prompt, avoid
lines starting with `---`, `## ` or `### ` — those end the section.

---

## Coding

## TASK: code-sku-parse
- area: coding
- max_tokens: 4000
- attach: none

### Prompt
Write a Python function `parse_sku(code: str) -> dict` for our SKU format:

    HH-<CATEGORY>-<NUMBER>[-<SIZE>]

- CATEGORY: exactly 3 uppercase ASCII letters (A-Z)
- NUMBER: exactly 5 ASCII digits (0-9); keep leading zeros
- SIZE: optional; one of S, M, L, XL

Return `{"category": ..., "number": ..., "size": ...}` with size `None` when absent. Ignore leading and trailing whitespace. Anything else — lowercase, wrong lengths, unknown sizes, extra parts, non-ASCII characters — must raise `ValueError`. Standard library only. Reply with the function in a single python code block.

### Good answer looks like
Passes `eval/checks/code-sku-parse.py`: 5 valid codes parsed exactly, 17 invalid codes rejected with `ValueError`. The two traps: Arabic-Indic digits (Python's `\d` matches them) and non-ASCII capitals like `Ä` (`str.isupper()` accepts them). A regex using `\d` or `isupper()` fails, even though it looks correct.

## TASK: code-abc-classify
- area: coding
- max_tokens: 4000
- attach: none

### Prompt
Write a Python function `abc_classify(items)` for our cycle-count planning. `items` is a list of `(sku, annual_value)` tuples. Return a dict mapping each sku to "A", "B" or "C":

1. Sort by annual_value descending; break ties by sku ascending.
2. Walk the sorted list keeping a running total of value.
3. An item is "A" if the running total *before* adding it is less than 80% of the grand total; otherwise "B" if that running total is less than 95%; otherwise "C".
4. If the grand total is 0, every item is "C". An empty list returns `{}`.

Do not modify the input list. Standard library only. Reply with the function in a single python code block.

### Good answer looks like
Passes `eval/checks/code-abc-classify.py`: the basic case, a tie where sku order decides the class, a zero total, a single item, an empty list, and the input left unmodified. The usual mistake is comparing the running total *after* adding the item, which misclassifies boundary items.

## TASK: code-business-days
- area: coding
- max_tokens: 4000
- attach: none

### Prompt
This function is used to compute SLA deadlines and gives wrong answers. Find every bug, explain each in one line, then give the corrected function in a single python code block. Keep the same name and signature style.

    from datetime import date, timedelta

    def business_days(start: date, end: date, holidays=set()) -> int:
        """Count working days in [start, end): our weekend is Friday and
        Saturday, and any date in `holidays` is also a day off.
        Returns 0 if end <= start."""
        days = 0
        d = start
        while d <= end:
            if d.weekday() not in (5, 6):
                days += 1
            d += timedelta(days=1)
        return days

### Good answer looks like
Names three real bugs: (1) `<=` includes `end`, but the range is half-open `[start, end)`; (2) `(5, 6)` is Saturday/Sunday, but Friday/Saturday is `(4, 5)`; (3) `holidays` is never checked. Flagging the mutable default `set()` is good practice, but it is not a bug here since the set is never mutated. The fixed function passes `eval/checks/code-business-days.py`.

## TASK: code-sql-top-customers
- area: coding
- max_tokens: 4000
- attach: none

### Prompt
SQLite schema:

    CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT);
    CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
                         order_date TEXT,   -- 'YYYY-MM-DD'
                         status TEXT);      -- 'open', 'shipped' or 'cancelled'
    CREATE TABLE order_lines (id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id),
                              product_id INTEGER, qty INTEGER, unit_price REAL,
                              discount REAL);  -- fraction between 0 and 1

Write one SQLite query returning the top 5 customers by 2025 net revenue. Net revenue is `qty * unit_price * (1 - discount)` summed over the customer's orders dated in 2025, excluding cancelled orders. Columns, in order: `customer_name`, `order_count` (number of distinct qualifying orders), `net_revenue` rounded to 2 decimals. Sort by net_revenue descending. Reply with the query in a single sql code block.

### Good answer looks like
Passes `eval/checks/code-sql-top-customers.py`, which compares the query's output against values computed independently in Python. Traps in the data: a huge cancelled order, large orders on 2024-12-31 and 2026-01-01, and multi-line orders. `COUNT(*)` instead of `COUNT(DISTINCT o.id)` inflates order_count roughly threefold.

## TASK: code-review
- area: coding
- max_tokens: 5000
- attach: none

### Prompt
Review this function before it goes to production. List the problems in order of severity, one line each with the reason, then give a corrected version in a single python code block.

    import sqlite3, json

    def export_customer_orders(db_path, customer_name, out_path, cache={}):
        if customer_name in cache:
            return cache[customer_name]
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(f"SELECT id FROM customers WHERE name = '{customer_name}'")
        row = cur.fetchone()
        orders = []
        for (order_id,) in cur.execute(f"SELECT id FROM orders WHERE customer_id = {row[0]}").fetchall():
            lines = conn.execute(f"SELECT qty, unit_price FROM order_lines WHERE order_id = {order_id}").fetchall()
            total = 0
            for qty, price in lines:
                total += qty * price
            orders.append({"order_id": order_id, "total": total})
        try:
            f = open(out_path, "w")
            f.write(json.dumps(orders))
        except:
            pass
        cache[customer_name] = orders
        return orders

### Good answer looks like
Seven planted problems. A good answer finds at least 5 of them, ranks SQL injection first, and invents none:
1. SQL injection via the f-string holding `customer_name`. Critical, and must be ranked first.
2. `row` is `None` for an unknown customer, so `row[0]` raises `TypeError`.
3. The bare `except: pass` swallows write failures, so data is silently lost.
4. The file is never closed (no `with`), so output may not be flushed.
5. The connection is never closed.
6. The mutable default `cache={}` is shared across calls and never invalidated. A cache hit also skips writing to a *new* `out_path`.
7. N+1 queries (one per order); a JOIN with GROUP BY does it in one.

The corrected version uses parameterised queries and `with` blocks, and handles a missing customer. Money stored as float is a fair minor point.

## TASK: code-reconcile
- area: coding
- max_tokens: 4000
- attach: none

### Prompt
Write `reconcile(ordered: dict[str, int], received: dict[str, int]) -> list[dict]` comparing purchase-order quantities with received quantities by SKU.

- A SKU is "on the order" if it is in `ordered` with a quantity above 0.
- For SKUs on the order, with `received` quantity r (0 if absent): r == 0 is "missing", 0 < r < ordered is "short", r > ordered is "over". An exact match is omitted.
- A SKU not on the order but received with quantity above 0 is "unexpected"; report its ordered quantity as 0.
- Anything else is omitted.

Each result is `{"sku", "ordered", "received", "issue"}`. Sort the list by sku. Do not modify the inputs. Standard library only. Reply with the function in a single python code block.

### Good answer looks like
Passes `eval/checks/code-reconcile.py`. The edge cases that separate careful from careless: received 0 is "missing" not "short", ordered 0 counts as not on the order, and unexpected SKUs appear at all (looping over `ordered` alone misses them).

---

## Report writing

## TASK: report-incident
- area: report
- max_tokens: 4000
- attach: none

### Prompt
Write an incident report for the operations director from these notes by the W4 night supervisor. Sections: Summary, Timeline, Impact, Cause, Actions taken, Next steps. Under 400 words. Use only what is in the notes.

Notes:
- 02:10 chiller 2 compressor stopped (from logger data, found later)
- 02:25 temp alarm on site dashboard, chiller 2 at 7.1 C
- alarm not acknowledged -- I was at dock 9 on a late inbound, dashboard screen is in the office only
- 05:40 alarm seen by morning receiving clerk, chiller 2 at 13.8 C
- 05:55 started moving stock to chiller 1 and chiller 3, done 07:20
- 38 pallets were in chiller 2: yogurt, white cheese, cream (mostly Luxor Dairy)
- quality inspector checked 08:30: 27 pallets OK (core probes stayed under 8 C), 11 pallets discarded (cream and yogurt on top racks)
- discarded stock value EGP 486,200 per WMS
- technician 09:15, compressor restarted, says probably the start relay but not confirmed, part ordered, arrives Tuesday
- chiller 2 out of use until repair; chillers 1 and 3 full, can't accept extra chilled inbound for 2 days
- alarm only shows on the office screen, nobody gets an SMS
- last maintenance on chiller 2 was in May

### Good answer looks like
- Every time and figure is exact: stop at 02:10, alarm at 02:25, seen at 05:40 (3 h 15 m unacknowledged), move from 05:55 to 07:20. 38 pallets affected, 27 kept, 11 discarded, EGP 486,200.
- The cause is stated as **suspected** (start relay, not confirmed), not as fact.
- The alarm reaching only the office screen, with no SMS, is identified as a contributing factor.
- Next steps: an escalation/SMS alert, the relay repair on Tuesday, and the 2-day chilled-inbound restriction.
- Nothing invented. In particular, it must not claim maintenance was overdue, since no schedule is given. Under 400 words.

## TASK: report-kpi-update
- area: report
- max_tokens: 3000
- attach: none

### Prompt
Write a monthly status update (max 250 words) for the regional director comparing September with August for warehouse W3. Lead with what needs attention.

| KPI | August | September | Target |
|---|---|---|---|
| Orders shipped | 12,480 | 13,910 | — |
| On-time dispatch | 91.2% | 87.5% | 95% |
| Pick accuracy | 99.1% | 99.3% | 99.0% |
| Damage claims | 14 | 22 | at most 15 |
| Overtime hours | 1,140 | 1,655 | — |

Context from the site manager: two experienced pickers were on leave for the last two weeks of September; a new customer (Nile Mart) went live on 8 September; the conveyor in zone B was down for 6 hours on 17 September.

### Good answer looks like
- Leads with on-time dispatch: down 3.7 points, and 7.5 below target.
- Correct derived figures: orders +1,430 (+11.5%); damage claims +8 (+57%) and above the ≤15 target; overtime +515 hours (+45%); pick accuracy fine and above target.
- The three context items are presented as *likely contributing* factors, not proven causes.
- No invented numbers. At most 250 words.

## TASK: report-customer-reply
- area: report
- max_tokens: 3000
- attach: none

### Prompt
Draft a reply to this customer email. Follow our policy and the internal facts. Do not reveal anything marked internal-only.

Customer email (from Hany Morsi, Procurement, Nile Mart):
"Our order SO-88213 was promised for 14 September and still hasn't arrived. This is the second late delivery this month and our stores are running out of stock. I need a firm delivery date today and I want to know what you are doing about compensation."

Internal facts:
- SO-88213 is 18 pallets, promised 14 September. Today is 18 September.
- Delay cause: our carrier's truck was held at Sokhna port for a customs inspection of another container on the same load. (Internal-only: the carrier is Falcon Freight — do not name them.)
- New confirmed delivery: 20 September, 07:00-11:00, dispatched from W6.
- The earlier late delivery this month (SO-87990) was 1 day late.
- Policy: a delivery more than 3 days late earns a 5% credit on that order's value, issued as a credit note within 7 days.
- Sign as: Mostafa Kamel, Account Manager.

### Good answer looks like
- Apologises and acknowledges that this is the second late delivery.
- Gives the firm date: 20 September, 07:00-11:00.
- Offers the 5% credit on SO-88213, since it will be 6 days late (more than 3), as a credit note within 7 days.
- Explains the cause generically (customs inspection at the port) and **does not name Falcon Freight**.
- Does not offer a credit for SO-87990 (1 day late, below the threshold).
- Signed Mostafa Kamel; professional tone; no invented commitments.

## TASK: report-meeting-actions
- area: report
- max_tokens: 3000
- attach: none

### Prompt
From this meeting transcript, list (1) the decisions made and (2) the action items, each with owner and due date. Only include what was actually agreed.

Weekly ops meeting, W1, Monday 22 September 2025. Attendees: Omar (site manager), Dina (inventory), Hany (transport), Rasha (HR), Wael (safety).

Omar: Let's start with the cycle count backlog. Dina, where are we?
Dina: We're 340 locations behind on class A counts. With two counters we can't catch up before quarter end.
Omar: Options?
Dina: Either we borrow two people from packing for a week, or we pause class C counts until October.
Hany: Packing can't spare anyone, we have the Nile Mart volume.
Omar: Then we pause class C counts until 1 October. Decision made. Dina, update the count plan in the WMS by Wednesday.
Dina: OK, by Wednesday the 24th.
Omar: Transport. Hany?
Hany: Two late departures last week because the yard was blocked. I want to propose a second yard marshal on the evening shift.
Rasha: We have budget for one temporary hire until December.
Omar: Fine, approved — a temporary evening yard marshal until the end of December. Rasha, can you post the job?
Rasha: I'll post it by Thursday.
Wael: Before we move on, I'd like to raise the forklift speed limit in the yard from 10 to 15 km/h to speed up loading.
Omar: I'm not comfortable with that before the new pedestrian lanes are painted.
Wael: Fair. Let's drop it for now.
Omar: Agreed, we're not changing the limit. Wael, when are the lanes being painted?
Wael: The contractor said 6 October. I'll confirm the date with them by Friday.
Omar: Good. Last item: the fire drill. It's overdue.
Wael: I can run it on 2 October.
Omar: Make it 1 October; the 2nd clashes with the Nile Mart peak. Decision: fire drill on 1 October, morning shift.
Wael: OK. I'll send the notice to all staff by Monday the 29th.
Omar: Hany, you were going to send the carrier scorecard?
Hany: I'll have it out by Friday the 26th. Actually, Dina has the late-delivery data; it makes more sense for her to own it.
Dina: Fine, I'll send it — but I need until Monday the 29th.
Omar: OK, Dina owns the scorecard, due the 29th. Anything else? No? Thanks, everyone.

### Good answer looks like
- **Decisions:** pause class C counts until 1 October; approve a temporary evening yard marshal until the end of December; fire drill on **1 October** (not the 2nd), morning shift; yard speed limit **not** changed. Listing the last as "decided not to change" is correct; listing it as an action is wrong.
- **Actions (exactly five):**
  - Dina: update the WMS count plan by Wed 24 Sep.
  - Rasha: post the yard marshal job by Thu 25 Sep.
  - Wael: confirm the lane-painting date by Fri 26 Sep.
  - Wael: send the fire drill notice by Mon 29 Sep.
  - **Dina** (not Hany): send the carrier scorecard by Mon 29 Sep (not the 26th).
- Converting weekday names to dates correctly is a plus.

## TASK: report-business-case
- area: report
- max_tokens: 4000
- attach: none

### Prompt
Write a one-page business case (max 350 words) for the W3 management team on whether to add a second shift for the next 6 months. Use only these figures and show the calculation.

- Second shift cost: EGP 185,000 per month (12 staff, a supervisor, utilities)
- Current overtime cost: EGP 142,000 per month; a second shift would eliminate about 80% of it
- Late-dispatch penalties paid to customers: EGP 61,000 per month on average; expected to fall by half with a second shift
- One-time training and setup cost: EGP 90,000
- Nothing else changes

### Good answer looks like
- Monthly savings: 0.8 × 142,000 = 113,600, plus 0.5 × 61,000 = 30,500, for 144,100.
- Net: 144,100 − 185,000 = **−40,900 per month**. Over 6 months, −245,400 − 90,000 = **−335,400**.
- On these figures, recommends *against*, or makes approval conditional on benefits not captured here.
- The trap is the naive calculation: 142,000 + 61,000 = 203,000 > 185,000 looks profitable, but it ignores the 80% and 50% factors and the setup cost. At most 350 words.

## TASK: report-rewrite-tone
- area: report
- max_tokens: 2500
- attach: none

### Prompt
Rewrite this email to a supplier so it is firm but professional. Keep every factual demand; remove insults and any threat not backed by a contract. Max 180 words.

"Honestly this is ridiculous. Your last THREE deliveries of stretch film were garbage - 40 rolls tore on the wrapper and my team wasted a whole shift. If you can't get your act together we'll dump you and tell everyone in the market how useless you are. I want replacements for the 40 rolls by 15 October, a credit note for the stretch film line on invoice RSP-2025-08817, and your quality manager on a call with us this week. Fix it."

### Good answer looks like
- Keeps all three demands exactly: 40 replacement rolls by 15 October; a credit note for the stretch-film line on RSP-2025-08817; a call with their quality manager this week.
- Keeps the facts: three deliveries, 40 rolls tore, a lost shift.
- Removes the insults and the threat to badmouth them in the market. Saying the supply relationship will be reviewed if problems continue is acceptable.
- At most 180 words.

---

## Long-document reasoning

Documents are generated by `eval/make_data.py`. Token counts are from the model's own tokenizer.

## TASK: longdoc-q3-late
- area: long-document
- max_tokens: 6000
- attach: eval/docs/shipment-register-2025.txt

### Prompt
Using only the shipment register above: which supplier had the most LATE deliveries in Q3 2025 (delivery dates from 1 July to 30 September inclusive), and how many? Also give the runner-up and its count. Rejected shipments do not count as late.

### Good answer looks like
Document: 136,649 tokens, 2,767 shipment lines, about 700 of them in Q3. **Sinai Beverages, 21**; runner-up **Red Sea Packaging, 14**.
- Exact counts: full marks.
- Correct ranking with counts within ±2: partial. This is counting across ~700 lines, which language models find genuinely hard.
- **Nile Plastics** is a fail: it is the full-year leader (48), with only 9 in Q3, so naming it means the date range was ignored.

## TASK: longdoc-rejections
- area: long-document
- max_tokens: 4000
- attach: eval/docs/shipment-register-2025.txt

### Prompt
List every REJECTED shipment in the register above: shipment id, date, supplier, warehouse and reason. State how many there are in total.

### Good answer looks like
Exactly 4, none invented:
- SHP-00141, 2025-01-19, Delta Paper Co., W5: seal broken on 4 pallets.
- SHP-00952, 2025-05-07, Luxor Dairy, W2: temperature 11.4 C on arrival.
- SHP-02221, 2025-10-22, Alex Electronics, W7: quantity did not match the ASN; missing serial labels.
- SHP-02748, 2025-12-29, Qasr Foods, W9: short remaining shelf life.

The last one sits 99.9% of the way through the document, which tests whether the end is read. This task shares a document with longdoc-q3-late, so prefix caching should make its prefill much faster; record whether it does.

## TASK: longdoc-termination
- area: long-document
- max_tokens: 3000
- attach: eval/docs/supply-agreement-luxor-dairy.txt

### Prompt
Under this agreement as it currently stands, how much notice must either party give to terminate for convenience? Cite the clause or clauses that establish it.

### Good answer looks like
Document: 75,099 tokens. **60 days.** Clause 19.3 originally said 90 days; Amendment No. 2 (dated 12 May 2025, effective 1 June 2025) replaced that with 60. The amendment is at the very end of the document. Answering 90 days fails, because it means the amendment was missed.

## TASK: longdoc-payment-conflict
- area: long-document
- max_tokens: 4000
- attach: eval/docs/supply-agreement-luxor-dairy.txt

### Prompt
Are the payment terms in this agreement internally consistent? If not, identify exactly where they conflict and which provision governs.

### Good answer looks like
- Conflict between **clause 8.2** (30 days from the *invoice date*) and **Schedule D, paragraph D.4** (45 days from *receipt of the Goods*). The period and the trigger both differ.
- **Clause 1.4** says the clauses prevail over the Schedules, so 8.2 governs. Citing 1.4 separates a careful answer from a lucky one.
- Mentioning the late-payment interest in 8.4 is fine. Inventing other conflicts is a deduction.

## TASK: longdoc-audit-manager
- area: long-document
- max_tokens: 4000
- attach: eval/docs/operations-manual-2025.txt

### Prompt
Which warehouse failed its March 2025 fire-safety audit? Who is that warehouse's site manager now, and what was the deadline for the corrective action?

### Good answer looks like
Document: 195,259 tokens, close to the 250K limit. Three hops:
- **W6, Ain Sokhna.** The audit is 76% of the way in.
- Its current manager is **Nadia Soliman**, appointed effective 15 June 2025 in the staffing update on the last lines. Karim Farouk, listed as manager in the overview at 0.2%, was manager at audit time and has moved to W2.
- Deadline **15 April 2025**.

Answering "Karim Farouk" is a partial: the retrieval worked but the end-of-document update was missed.

## TASK: longdoc-all-audit-failures
- area: long-document
- max_tokens: 5000
- attach: eval/docs/operations-manual-2025.txt

### Prompt
List every audit category that any warehouse FAILED in 2025, with the warehouse, the quarter and the corrective-action deadline.

### Good answer looks like
Exactly 5, none invented:
- Q1: W2 Inventory accuracy, 2025-04-30.
- Q1: W6 Fire safety, 2025-04-15.
- Q1: W9 Cold chain, 2025-04-10.
- Q2: W8 Fire safety, 2025-07-15.
- Q2: W2 Documentation, 2025-07-31.

This shares a document with longdoc-audit-manager, so it tests prefix caching at about 195K tokens.

---

## Vision

Images are generated by `eval/make_data.py`: scan-style noise and rotation on the invoices, a handwritten remark on the delivery note, and a label rotated 90°.

## TASK: vision-invoice-extract
- area: vision
- max_tokens: 3000
- attach: eval/images/invoice-RSP-2025-08817.jpg

### Prompt
Extract this invoice as JSON with keys: supplier, invoice_number, invoice_date, due_date, po_reference, line_items (a list of objects with code, description, qty, unit_price, amount), subtotal, vat, total. Write numbers as plain numbers without thousands separators. Output only the JSON.

### Good answer looks like
Passes `eval/checks/vision-invoice-extract.py`: Red Sea Packaging S.A.E., RSP-2025-08817, 2025-09-03, due 2025-10-03, PO-45120. Exactly 5 lines (CB-4030 1200 × 6.75 = 8100; SF-23500 85 × 214 = 18190; PL-A5 5000 × 0.42 = 2100; PT-48 360 × 18.50 = 6660; EP-100 900 × 3.20 = 2880). Subtotal 37930.00, VAT 5310.20, total 43240.20.

## TASK: vision-invoice-audit
- area: vision
- max_tokens: 3000
- attach: eval/images/invoice-GH-11932.jpg

### Prompt
Check the arithmetic on this invoice, line by line and in the totals. Report any error, the correct figure, and what the correct invoice total should be.

### Good answer looks like
- **SB-20 Shelf bracket:** 48 × 37.50 = 1,800.00, not the printed 1,900.00.
- Corrected: subtotal 22,980.00, VAT 3,217.20, total **26,197.20**. The overcharge is 114.00 (100 plus 14 VAT).
- The printed VAT (3,231.20) is correctly 14% of the printed subtotal; it is wrong only as a consequence. Flagging other lines as wrong is a deduction.

## TASK: vision-delivery-check
- area: vision
- max_tokens: 3000
- attach: eval/images/delivery-note-DN-77410.jpg

### Prompt
This delivery note arrived against our purchase order PO-45388, which was:
- LD-1004 Full-cream milk 1 L: 480
- LD-1013 Plain yogurt 170 g: 1,200
- LD-1021 White cheese 500 g: 300
- LD-1033 Butter 200 g: 240
- LD-1041 Cooking cream 200 ml: 360

List every discrepancy between the order and the delivery note, including anything written by hand.

### Good answer looks like
- Yogurt is **short by 120** (1,080 delivered against 1,200 ordered).
- **Cooking cream LD-1041 is missing entirely** (360).
- **Low-fat milk LD-1007, 120 units, delivered but not ordered.**
- **Handwritten:** 2 cartons of butter crushed and refused, signed M. Adel, so fewer than 240 butter units were actually accepted.
- Milk and cheese match. All four discrepancies are needed for full marks.

## TASK: vision-chart-read
- area: vision
- max_tokens: 2500
- attach: eval/images/ontime-chart-2025.png

### Prompt
Read this chart. Which month had the lowest on-time rate, and approximately what was it? Which months were below the target line? Summarise the trend in two sentences.

### Good answer looks like
- **August, about 78%** (±2).
- Below target: **July (~88), August (~78), September (~86), October (~87)**. Exactly four months.
- Trend: steady above target January–June (91–94); a dip July–October bottoming in August; recovery in November–December (92–94).
- The bars carry no value labels, so values must be read from the gridlines, which are every 5 points.

## TASK: vision-terminal-debug
- area: vision
- max_tokens: 3000
- attach: eval/images/terminal-stock-sync.png

### Prompt
My script crashed. What is the cause, and what exactly should I change?

### Good answer looks like
- Notices that the CSV header (from the `head` output) spells the column **`qty_onhand`**, while the code at `stock_sync.py` line 57, in `sync_rows`, reads **`row["qty_on_hand"]`**.
- Fix: use the real column name, or normalise headers. Accepting both spellings is a fair robustness suggestion.
- A generic answer ("the key is missing, use `.get()`") that misses the spelling difference fails. `.get()` would just pass `None` into `int()`.

## TASK: vision-label-read
- area: vision
- max_tokens: 2500
- attach: eval/images/shipping-label.jpg

### Prompt
Read this shipping label. Give the tracking number, destination warehouse and dock, weight, and piece count. Is this the complete shipment?

### Good answer looks like
- Tracking **HH7-2025-0921-44817** exactly.
- **W7 Ismailia, Gate 3, Dock 12**; **18.6 kg**; **2 of 3**.
- **Not complete**: this is piece 2 of 3, so one piece is outstanding or labelled separately.
- The label is rotated 90° and slightly skewed; reading it correctly is the test.
