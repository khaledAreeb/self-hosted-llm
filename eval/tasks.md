# Evaluation set — Qwen3.8-27B capability

> **STATUS: TEMPLATE. Not yet a real evaluation set.**
> The entries below marked `FORMAT EXAMPLE` only show the structure. Replace
> them with real tasks from the company's actual work. Generic prompts produce
> a verdict nobody will act on — the value of this file is that the tasks are
> *yours*.

## Requirements (from `tasks.md`, group 4)

- [ ] 20-40 tasks in total across the four areas below
- [ ] every task is a **real** piece of company work, not a generic instruction
- [ ] every task states **what a good answer looks like** before it is run
- [ ] at least **3 long-document** tasks using real documents over 50,000 tokens
- [ ] at least **3 vision** tasks using real images — invoices, delivery notes,
      screenshots, photos of damaged goods
- [ ] **no agentic coding** — already measured: 63 requests over 10-20 minutes
      for two OpenCode sessions, so the answer is known

## Format

Each task is a `## TASK:` heading followed by fields. `eval/run_eval.py` parses
this file, so keep the structure exactly.

```
## TASK: <unique-id>
- area: coding | report | long-document | vision
- max_tokens: <number>
- attach: <path to a document or image, or "none">

### Prompt
<exactly what gets sent to the model>

### Good answer looks like
<written BEFORE running -- what would make you trust the answer?>
```

`attach` rules:
- **long-document**: a `.txt` or `.md` file under `eval/docs/`, prepended to the prompt
- **vision**: an image under `eval/images/` (`.png`, `.jpg`, `.jpeg`, `.webp`)
- otherwise `none`

`max_tokens` note: thinking is on at `reasoning_effort: low`. Reasoning
consumes part of the budget, so generative tasks should allow at least 2,000.
Under `medium`, a 300-word answer needed ~3,500.

---

## Coding

## TASK: code-EXAMPLE
- area: coding
- max_tokens: 3000
- attach: none

### Prompt
FORMAT EXAMPLE — replace with a real coding task from your team, e.g. a
function you actually needed, a bug you actually fixed, or a script you
actually wrote. Paste the real context the model would need.

### Good answer looks like
FORMAT EXAMPLE — state the concrete criteria: does it run, does it handle the
edge case you know about, does it match your codebase's conventions.

---

## Report writing

## TASK: report-EXAMPLE
- area: report
- max_tokens: 4000
- attach: none

### Prompt
FORMAT EXAMPLE — replace with a real report someone at the company had to
write: a status update, an incident summary, a client-facing explanation.
Give it the same raw material a colleague would have had.

### Good answer looks like
FORMAT EXAMPLE — could it be sent with light edits? Is anything factually
invented? Is the tone right for the actual audience?

---

## Long-document reasoning

## TASK: longdoc-EXAMPLE
- area: long-document
- max_tokens: 3000
- attach: eval/docs/REPLACE-ME.txt

### Prompt
FORMAT EXAMPLE — ask something that can only be answered by reading the whole
document: a clause buried on page 40, a contradiction between two sections, a
figure mentioned once near the end.

### Good answer looks like
FORMAT EXAMPLE — the specific facts the answer must contain, and where in the
document they are. Knowing the location lets you tell retrieval from guessing.

---

## Vision

## TASK: vision-EXAMPLE
- area: vision
- max_tokens: 2000
- attach: eval/images/REPLACE-ME.jpg

### Prompt
FORMAT EXAMPLE — e.g. "Extract the invoice number, supplier, total and due date
from this invoice as JSON." Use a real scanned document, not a clean digital one;
scans are what people actually have.

### Good answer looks like
FORMAT EXAMPLE — the exact values that should come back. Vision is the one
capability no other model in the fleet offers, so this is where the
deployment's value has to be proven.
