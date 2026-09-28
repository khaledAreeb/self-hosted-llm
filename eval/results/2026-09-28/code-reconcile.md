# code-reconcile (coding)

| metric | value |
|---|---|
| prompt_tokens | 231 |
| completion_tokens | 913 |
| reasoning_tokens | 664 |
| ttft_s | 0.83 |
| total_s | 7.58 |
| finish_reason | stop |
| answer_words | 95 |
| empty_answer | False |
| truncated | False |

attach: `none`  max_tokens: 4000

## Prompt

Write `reconcile(ordered: dict[str, int], received: dict[str, int]) -> list[dict]` comparing purchase-order quantities with received quantities by SKU.

- A SKU is "on the order" if it is in `ordered` with a quantity above 0.
- For SKUs on the order, with `received` quantity r (0 if absent): r == 0 is "missing", 0 < r < ordered is "short", r > ordered is "over". An exact match is omitted.
- A SKU not on the order but received with quantity above 0 is "unexpected"; report its ordered quantity as 0.
- Anything else is omitted.

Each result is `{"sku", "ordered", "received", "issue"}`. Sort the list by sku. Do not modify the inputs. Standard library only. Reply with the function in a single python code block.

## Good answer looks like (written before running)

Passes `eval/checks/code-reconcile.py`. The edge cases that separate careful from careless: received 0 is "missing" not "short", ordered 0 counts as not on the order, and unexpected SKUs appear at all (looping over `ordered` alone misses them).

## Answer

```python
def reconcile(ordered: dict[str, int], received: dict[str, int]) -> list[dict]:
    results = []
    all_skus = set(ordered) | set(received)

    for sku in all_skus:
        o = ordered.get(sku, 0)
        r = received.get(sku, 0)
        on_order = sku in ordered and o > 0

        if on_order:
            if r == 0:
                results.append({"sku": sku, "ordered": o, "received": r, "issue": "missing"})
            elif r < o:
                results.append({"sku": sku, "ordered": o, "received": r, "issue": "short"})
            elif r > o:
                results.append({"sku": sku, "ordered": o, "received": r, "issue": "over"})
        elif r > 0:
            results.append({"sku": sku, "ordered": 0, "received": r, "issue": "unexpected"})

    results.sort(key=lambda x: x["sku"])
    return results
```

## Reasoning

Let me break down the requirements:

1. `ordered` is a dict mapping SKU -> ordered quantity
2. `received` is a dict mapping SKU -> received quantity
3. A SKU is "on the order" if it's in `ordered` with quantity > 0
4. For SKUs on the order:
   - r = received.get(sku, 0)
   - r == 0 → "missing"
   - 0 < r < ordered → "short"
   - r > ordered → "over"
   - r == ordered → omitted
5. A SKU not on the order (not in `ordered` or in `ordered` with quantity <= 0) but in `received` with quantity > 0 → "unexpected", report ordered as 0
6. Everything else is omitted
7. Each result: `{"sku", "ordered", "received", "issue"}`
8. Sort by sku
9. Don't modify inputs
10. Standard library only

Let me think about edge cases:
- A SKU in `ordered` with quantity 0 or negative: not "on the order"
- A SKU in `ordered` with quantity 0 and also in `received` with quantity > 0: this is "unexpected" (not on the order, but received)
- A SKU in `ordered` with quantity 0 and in `received` with quantity 0: omitted (not on order, not received with > 0)

Let me write this:

```python
def reconcile(ordered: dict[str, int], received: dict[str, int]) -> list[dict]:
    results = []
    
    # All SKUs to consider
    all_skus = set(ordered.keys()) | set(received.keys())
    
    for sku in all_skus:
        o = ordered.get(sku, 0)
        r = received.get(sku, 0)
        
        on_order = sku in ordered and o > 0
        
        if on_order:
            if r == 0:
                results.append({"sku": sku, "ordered": o, "received": r, "issue": "missing"})
            elif 0 < r < o:
                results.append({"sku": sku, "ordered": o, "received": r, "issue": "short"})
            elif r > o:
                results.append({"sku": sku, "ordered": o, "received": r, "issue": "over"})
            # r == o: omitted
        else:
            # Not on the order
            if r > 0:
                results.append({"sku": sku, "ordered": 0, "received": r, "issue": "unexpected"})
            # else: omitted
    
    results.sort(key=lambda x: x["sku"])
    return results
```

This looks correct. Let me verify:
- Doesn't modify inputs: we only read from them, create new dicts. ✓
- Standard library only: no imports needed. ✓
- Sorted by sku. ✓
- All cases covered. ✓
