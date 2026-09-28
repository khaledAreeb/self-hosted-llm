# code-sku-parse (coding)

| metric | value |
|---|---|
| prompt_tokens | 189 |
| completion_tokens | 1674 |
| reasoning_tokens | 1323 |
| ttft_s | 4.6 |
| total_s | 18.28 |
| finish_reason | stop |
| answer_words | 153 |
| empty_answer | False |
| truncated | False |

attach: `none`  max_tokens: 4000

## Prompt

Write a Python function `parse_sku(code: str) -> dict` for our SKU format:

    HH-<CATEGORY>-<NUMBER>[-<SIZE>]

- CATEGORY: exactly 3 uppercase ASCII letters (A-Z)
- NUMBER: exactly 5 ASCII digits (0-9); keep leading zeros
- SIZE: optional; one of S, M, L, XL

Return `{"category": ..., "number": ..., "size": ...}` with size `None` when absent. Ignore leading and trailing whitespace. Anything else — lowercase, wrong lengths, unknown sizes, extra parts, non-ASCII characters — must raise `ValueError`. Standard library only. Reply with the function in a single python code block.

## Good answer looks like (written before running)

Passes `eval/checks/code-sku-parse.py`: 5 valid codes parsed exactly, 17 invalid codes rejected with `ValueError`. The two traps: Arabic-Indic digits (Python's `\d` matches them) and non-ASCII capitals like `Ä` (`str.isupper()` accepts them). A regex using `\d` or `isupper()` fails, even though it looks correct.

## Answer

```python
import re

def parse_sku(code: str) -> dict:
    code = code.strip()
    m = re.fullmatch(r'HH-([A-Z]{3})-([0-9]{5})(?:-(S|M|L|XL))?', code)
    if not m:
        raise ValueError(f"Invalid SKU: {code!r}")
    return {
        "category": m.group(1),
        "number": m.group(2),
        "size": m.group(3),
    }
```

**How it works:**

| Step | Detail |
|------|--------|
| `strip()` | Removes leading/trailing whitespace before matching. |
| `re.fullmatch` | Anchors the pattern to the entire string (equivalent to `^…$` but stricter — no trailing-newline edge case). |
| `HH-` | Literal prefix. |
| `([A-Z]{3})` | Exactly 3 uppercase ASCII letters; captures the category. |
| `([0-9]{5})` | Exactly 5 ASCII digits; captures the number as a string (preserving leading zeros). |
| `(?:-(S\|M\|L\|XL))?` | Optional non-capturing group for the size; the inner group captures `S`, `M`, `L`, or `XL`, or is `None` when absent. |

Any deviation — wrong prefix, lowercase, wrong lengths, unknown size, extra segments, non-ASCII lookalikes — causes `fullmatch` to return `None`, triggering the `ValueError`.

## Reasoning

Let me break down the SKU format:

`HH-<CATEGORY>-<NUMBER>[-<SIZE>]`

- Starts with literal `HH-`
- CATEGORY: exactly 3 uppercase ASCII letters (A-Z)
- NUMBER: exactly 5 ASCII digits (0-9), keep leading zeros (so return as string)
- SIZE: optional, one of S, M, L, XL

I need to:
1. Strip leading/trailing whitespace
2. Parse the format strictly
3. Return a dict with keys "category", "number", "size"
4. Raise ValueError for anything invalid

Let me think about the approach:

1. Strip whitespace
2. Split by `-`
3. Check that the first part is exactly "HH"
4. Check that there are exactly 3 or 4 parts (3 if no size, 4 if size present)
5. Validate each part

Let me think about edge cases:
- "HH-ABC-12345" → valid, size is None
- "HH-ABC-12345-S" → valid, size is "S"
- "HH-ABC-12345-XL" → valid, size is "XL"
- "HH-abc-12345" → invalid (lowercase)
- "HH-AB-12345" → invalid (category too short)
- "HH-ABCD-12345" → invalid (category too long)
- "HH-ABC-1234" → invalid (number too short)
- "HH-ABC-123456" → invalid (number too long)
- "HH-ABC-12345-X" → invalid (unknown size)
- "HH-ABC-12345-S-M" → invalid (extra parts)
- "hh-ABC-12345" → invalid (lowercase HH)
- "HH-ABC-12345-" → invalid (trailing dash means empty part)
- "HH--12345" → invalid (empty category)

I could use regex or manual parsing. Let me use regex for clarity:

Pattern: `^HH-([A-Z]{3})-([0-9]{5})(?:-(S|M|L|XL))?$`

This should work. Let me verify:
- `HH-ABC-12345` → matches, groups: ABC, 12345, None
- `HH-ABC-12345-S` → matches, groups: ABC, 12345, S
- `HH-ABC-12345-XL` → matches, groups: ABC, 12345, XL
- `HH-abc-12345` → no match (lowercase)
- `HH-AB-12345` → no match
- `HH-ABCD-12345` → no match
- `HH-ABC-1234` → no match
- `HH-ABC-123456` → no match
- `HH-ABC-12345-X` → no match
- `HH-ABC-12345-S-M` → no match (the $ anchor prevents extra parts)

Wait, what about non-ASCII characters? The regex `[A-Z]` in Python by default matches only ASCII A-Z (since we're not using the `re.UNICODE` flag... actually in Python 3, `re` patterns are unicode by default, but `[A-Z]` still only matches ASCII A-Z because it's a range specification). Let me verify: in Python 3, `[A-Z]` matches only the characters A through Z (ASCII), not any other Unicode characters that might look like uppercase letters. So that's fine.

Similarly `[0-9]` matches only ASCII digits 0-9.

What about something like `HH-ＡＢＣ-12345` (fullwidth characters)? The `[A-Z]` won't match those, so it'll correctly raise ValueError.

Let me write the function:

```python
import re

def parse_sku(code: str) -> dict:
    if not isinstance(code, str):
        raise ValueError("code must be a string")
    
    code = code.strip()
    
    pattern = r'^HH-([A-Z]{3})-([0-9]{5})(?:-(S|M|L|XL))?$'
    m = re.match(pattern, code)
    
    if not m:
        raise ValueError(f"Invalid SKU: {code!r}")
    
    return {
        "category": m.group(1),
        "number": m.group(2),
        "size": m.group(3),
    }
```

Wait, should I check if `code` is a string? The type hint says `str`, so maybe I don't need to. But it's defensive. Actually, the problem says "Anything else... must raise ValueError", so if someone passes a non-string, should I raise ValueError? The type hint says `str`, so I'll assume it's always a string. But let me keep it simple and not add that check since the type hint guarantees it.

Actually, let me reconsider. The problem says "Standard library only" and "Reply with the function in a single python code block." So I should include the import.

Let me also think about whether `re.match` with `$` is sufficient or if I need `\Z`. In Python, `$` can match before a trailing newline. So `"HH-ABC-12345\n"` would match with `$` but not with `\Z`. However, we're stripping whitespace first, so the trailing newline would be removed. So `$` is fine after stripping.

Wait, actually `strip()` removes all whitespace including newlines, so after stripping, there won't be a trailing newline. So `$` is safe here.

Let me finalize the solution.
