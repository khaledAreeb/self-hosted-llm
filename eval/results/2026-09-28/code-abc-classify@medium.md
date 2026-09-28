# code-abc-classify@medium (coding)

| metric | value |
|---|---|
| prompt_tokens | 183 |
| completion_tokens | 1303 |
| reasoning_tokens | 1111 |
| ttft_s | 0.8 |
| total_s | 10.55 |
| finish_reason | stop |
| answer_words | 80 |
| empty_answer | False |
| truncated | False |

attach: `none`  max_tokens: 16000

## Prompt

Write a Python function `abc_classify(items)` for our cycle-count planning. `items` is a list of `(sku, annual_value)` tuples. Return a dict mapping each sku to "A", "B" or "C":

1. Sort by annual_value descending; break ties by sku ascending.
2. Walk the sorted list keeping a running total of value.
3. An item is "A" if the running total *before* adding it is less than 80% of the grand total; otherwise "B" if that running total is less than 95%; otherwise "C".
4. If the grand total is 0, every item is "C". An empty list returns `{}`.

Do not modify the input list. Standard library only. Reply with the function in a single python code block.

## Good answer looks like (written before running)

Passes `eval/checks/code-abc-classify.py`: the basic case, a tie where sku order decides the class, a zero total, a single item, an empty list, and the input left unmodified. The usual mistake is comparing the running total *after* adding the item, which misclassifies boundary items.

## Answer

```python
def abc_classify(items):
    if not items:
        return {}

    grand_total = sum(value for _, value in items)

    if grand_total == 0:
        return {sku: "C" for sku, _ in items}

    sorted_items = sorted(items, key=lambda x: (-x[1], x[0]))

    threshold_a = 0.8 * grand_total
    threshold_b = 0.95 * grand_total

    result = {}
    running_total = 0

    for sku, value in sorted_items:
        if running_total < threshold_a:
            result[sku] = "A"
        elif running_total < threshold_b:
            result[sku] = "B"
        else:
            result[sku] = "C"
        running_total += value

    return result
```

## Reasoning

Let me carefully parse the requirements:

1. `items` is a list of `(sku, annual_value)` tuples.
2. Sort by `annual_value` descending, break ties by `sku` ascending.
3. Walk the sorted list keeping a running total of value.
4. Classification logic:
   - "A" if the running total *before* adding the current item is less than 80% of the grand total
   - "B" if that running total is less than 95% of the grand total
   - "C" otherwise
5. If grand total is 0, every item is "C".
6. Empty list returns `{}`.
7. Do not modify the input list.
8. Standard library only.

Let me think through the logic carefully:

- Grand total = sum of all annual_values
- Sort: `sorted(items, key=lambda x: (-x[1], x[0]))`
- Walk through sorted list:
  - `running_total` starts at 0
  - For each item:
    - Check `running_total` (before adding current item's value)
    - If `running_total < 0.8 * grand_total` → "A"
    - Elif `running_total < 0.95 * grand_total` → "B"
    - Else → "C"
    - Then add current item's value to `running_total`

Wait, let me re-read: "An item is 'A' if the running total *before* adding it is less than 80% of the grand total; otherwise 'B' if that running total is less than 95%; otherwise 'C'."

So the classification is based on the running total BEFORE adding the current item. That makes sense - it's like: if we haven't yet accumulated 80% of the total, this item is still in the "A" zone. Once we've passed 80%, we're in "B" zone. Once we've passed 95%, we're in "C" zone.

Let me trace through an example:
- Items: [("A", 50), ("B", 30), ("C", 10), ("D", 10)]
- Grand total = 100
- 80% = 80, 95% = 95
- Sorted: [("A", 50), ("B", 30), ("C", 10), ("D", 10)] (C and D tie at 10, sorted by sku ascending)
- Walk:
  - Item A: running_total = 0. 0 < 80 → "A". running_total becomes 50.
  - Item B: running_total = 50. 50 < 80 → "A". running_total becomes 80.
  - Item C: running_total = 80. 80 < 80? No. 80 < 95? Yes → "B". running_total becomes 90.
  - Item D: running_total = 90. 90 < 80? No. 90 < 95? Yes → "B". running_total becomes 100.

Result: {"A": "A", "B": "A", "C": "B", "D": "B"}

That looks correct.

Edge cases:
- Grand total is 0: all items are "C"
- Empty list: return {}

Let me also consider: what if there are duplicate SKUs? The problem says "Return a dict mapping each sku to..." - I'll assume SKUs are unique, but if not, the last one in the sorted order would win in the dict. I'll just use a dict assignment.

Let me write the function:

```python
def abc_classify(items):
    if not items:
        return {}
    
    grand_total = sum(value for _, value in items)
    
    if grand_total == 0:
        return {sku: "C" for sku, _ in items}
    
    sorted_items = sorted(items, key=lambda x: (-x[1], x[0]))
    
    result = {}
    running_total = 0
    threshold_a = 0.8 * grand_total
    threshold_b = 0.95 * grand_total
    
    for sku, value in sorted_items:
        if running_total < threshold_a:
            result[sku] = "A"
        elif running_total < threshold_b:
            result[sku] = "B"
        else:
            result[sku] = "C"
        running_total += value
    
    return result
```

This looks correct. Let me verify:
- Doesn't modify input list (uses `sorted()` which creates a new list)
- Standard library only (no imports needed)
- Handles empty list
- Handles grand total of 0
- Sorts by annual_value descending, ties by sku ascending
- Uses running total before adding current item for classification

I think this is solid.
