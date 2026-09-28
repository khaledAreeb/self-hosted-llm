# vision-terminal-debug (vision)

| metric | value |
|---|---|
| prompt_tokens | 837 |
| completion_tokens | 719 |
| reasoning_tokens | 317 |
| ttft_s | 1.43 |
| total_s | 7.9 |
| finish_reason | stop |
| answer_words | 210 |
| empty_answer | False |
| truncated | False |

attach: `eval/images/terminal-stock-sync.png`  max_tokens: 3000

## Prompt

My script crashed. What is the cause, and what exactly should I change?

## Good answer looks like (written before running)

- Notices that the CSV header (from the `head` output) spells the column **`qty_onhand`**, while the code at `stock_sync.py` line 57, in `sync_rows`, reads **`row["qty_on_hand"]`**.
- Fix: use the real column name, or normalise headers. Accepting both spellings is a fair robustness suggestion.
- A generic answer ("the key is missing, use `.get()`") that misses the spelling difference fails. `.get()` would just pass `None` into `int()`.

## Answer

## Cause

A **column‑name mismatch** between your code and the CSV header.

- Your code (line 57) reads: `row["qty_on_hand"]`
- The actual CSV header is: `sku,description,location,qty_onhand,uom`

The file's column is named **`qty_onhand`** (no underscore between *on* and *hand*), but the script looks up **`qty_on_hand`**. Since that key doesn't exist in the row's dict, `csv.DictReader` raises `KeyError: 'qty_on_hand'`.

## The exact change

In `/opt/hh/stock_sync.py`, line 57, change the key to match the header:

```python
# before
qty = int(row["qty_on_hand"])

# after
qty = int(row["qty_onhand"])
```

That single edit fixes the crash.

## Optional: make it robust against this class of bug

If the export format can drift, you can guard the lookup so a typo or renamed column fails with a clear message (or a default) instead of a bare `KeyError`:

```python
qty = int(row.get("qty_onhand", 0))          # default to 0 if missing
# or, to fail loudly with context:
if "qty_onhand" not in row:
    raise ValueError(f"Missing 'qty_onhand' in row: {row}")
qty = int(row["qty_onhand"])
```

You may also want to scan the rest of `sync_rows` for other hardcoded keys (`sku`, `location`, `uom`, etc.) and confirm each matches the header exactly — the same kind of off‑by‑one‑underscore typo could bite you on a later column.

**TL;DR:** rename `qty_on_hand` → `qty_onhand` on line 57.

## Reasoning

The user has a Python script that crashed with a KeyError. Let me look carefully at the evidence in the screenshot.

The traceback shows:
- Line 57 in `sync_rows`: `qty = int(row["qty_on_hand"])`
- `KeyError: 'qty_on_hand'`

Then they ran `head -3` on the CSV file, which shows the header row:
`sku,description,location,qty_onhand,uom`

So the actual column name in the CSV is `qty_onhand` (no underscore between "on" and "hand"), but the code is looking for `qty_on_hand` (with an underscore). That's the mismatch causing the KeyError.

The fix: change `row["qty_on_hand"]` to `row["qty_onhand"]` on line 57.

I should be precise and direct. The cause is a column-name mismatch. The exact change is on line 57. I'll provide the before/after. I could also mention a defensive alternative (e.g., normalizing keys or using a fallback), but the user asked "what exactly should I change," so the primary answer is the one-line fix. I'll keep it focused but add a brief note about robustness optionally.

Let me make sure I read the header correctly: `sku,description,location,qty_onhand,uom`. Yes, `qty_onhand`. The code uses `qty_on_hand`. Confirmed.

I'll write a concise, self-contained response.
