# code-abc-classify (coding)

| metric | value |
|---|---|
| prompt_tokens | 213 |
| completion_tokens | 1111 |
| reasoning_tokens | 919 |
| ttft_s | 0.95 |
| total_s | 9.97 |
| finish_reason | stop |
| answer_words | 80 |
| empty_answer | False |
| truncated | False |

attach: `none`  max_tokens: 4000

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

## Reasoning

Let me break down the requirements:

1. Input: list of `(sku, annual_value)` tuples
2. Sort by `annual_value` descending, ties broken by `sku` ascending
3. Walk the sorted list with a running total
4. Classification logic:
   - "A" if running total *before* adding the current item < 80% of grand total
   - "B" if running total *before* adding the current item < 95% of grand total
   - "C" otherwise
5. Edge cases: grand total is 0 → all "C"; empty list → `{}`
6. Don't modify input list
7. Standard library only

Let me think through the logic carefully:

- Sort: `sorted(items, key=lambda x: (-x[1], x[0]))` — this gives descending by value, ascending by sku for ties.
- Grand total: sum of all annual values
- If grand total is 0, return all "C"
- Walk through sorted list, maintaining `running_total`
- For each item, check `running_total` (before adding current item's value):
  - If `running_total < 0.8 * grand_total` → "A"
  - Elif `running_total < 0.95 * grand_total` → "B"
  - Else → "C"
- Then add current item's value to `running_total`

Let me trace through an example to verify:
- Items: [("A", 50), ("B", 30), ("C", 20)]
- Grand total = 100
- 80% = 80, 95% = 95
- Sorted: [("A", 50), ("B", 30), ("C", 20)]
- Item "A": running_total = 0, 0 < 80 → "A", running_total becomes 50
- Item "B": running_total = 50, 50 < 80 → "A", running_total becomes 80
- Item "C": running_total = 80, 80 < 80? No. 80 < 95? Yes → "B", running_total becomes 100

That seems reasonable for ABC classification.

Let me also consider: what if annual_value can be negative? The problem says "annual_value" so I'll assume non-negative, but the logic should still work. If grand total is 0 (all zeros or empty), return all "C" or empty dict.

Wait, what if grand total is 0 but there are items? The spec says "If the grand total is 0, every item is 'C'." So I need to handle that case.

What about negative values making grand total 0? I'll just follow the spec literally: if grand_total == 0, all "C".

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
- Doesn't modify input (uses `sorted()` which returns a new list)
- Standard library only (no imports needed)
- Handles empty list
- Handles grand total of 0
- Sort is correct: descending by value, ascending by sku for ties
- Running total is checked *before* adding current item

I'm satisfied with this solution.
