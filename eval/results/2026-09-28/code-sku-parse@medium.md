# code-sku-parse@medium (coding)

| metric | value |
|---|---|
| prompt_tokens | 159 |
| completion_tokens | 2132 |
| reasoning_tokens | 1811 |
| ttft_s | 0.85 |
| total_s | 18.49 |
| finish_reason | stop |
| answer_words | 140 |
| empty_answer | False |
| truncated | False |

attach: `none`  max_tokens: 16000

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

- `code.strip()` handles leading/trailing whitespace.
- `re.fullmatch` anchors the pattern to the entire string (no partial matches, no trailing newline ambiguity).
- `HH-` is a literal prefix.
- `([A-Z]{3})` — exactly three uppercase ASCII letters (non-ASCII lookalikes like `Å` won't match).
- `([0-9]{5})` — exactly five ASCII digits; leading zeros are preserved as-is in the captured group.
- `(?:-(S|M|L|XL))?` — optional size segment; the non-capturing group keeps the dash out of the result, and the alternation restricts to the four valid sizes.
- Any deviation (lowercase, wrong lengths, unknown size, extra `-` segments, non-ASCII characters, empty parts) causes `fullmatch` to return `None`, triggering the `ValueError`.

## Reasoning

Let me analyze the SKU format:

`HH-<CATEGORY>-<NUMBER>[-<SIZE>]`

- Starts with "HH-"
- CATEGORY: exactly 3 uppercase ASCII letters (A-Z)
- NUMBER: exactly 5 ASCII digits (0-9), keep leading zeros
- SIZE: optional, one of S, M, L, XL
- Ignore leading and trailing whitespace
- Anything else must raise ValueError

Let me think about the parsing:

1. Strip leading/trailing whitespace
2. Split by "-"
3. First part must be "HH"
4. Second part must be exactly 3 uppercase ASCII letters
5. Third part must be exactly 5 ASCII digits
6. Fourth part (optional) must be one of S, M, L, XL
7. No extra parts allowed

Let me think about edge cases:
- "HH-ABC-12345" → valid, size is None
- "HH-ABC-12345-S" → valid, size is "S"
- "HH-ABC-12345-XL" → valid, size is "XL"
- "HH-abc-12345" → invalid (lowercase)
- "HH-AB-12345" → invalid (wrong length category)
- "HH-ABC-1234" → invalid (wrong length number)
- "HH-ABC-12345-X" → invalid (unknown size)
- "HH-ABC-12345-S-M" → invalid (extra parts)
- "HH-ABC-12345-" → invalid (empty size part)
- "HH-ABC-12345-SL" → invalid (unknown size)
- "HH-ABC-12345-s" → invalid (lowercase size)

I need to be careful about:
- Non-ASCII characters: I should check that characters are actually ASCII. Using regex with explicit ranges or checking ord() values.
- The "HH" prefix must be exactly "HH" (uppercase)
- Splitting by "-" - if there are extra dashes, that's invalid

Let me use a regex approach or manual parsing. Let me go with manual parsing for clarity, but I could also use regex.

Actually, let me use a regex for the whole thing:

`^HH-([A-Z]{3})-([0-9]{5})(?:-(S|M|L|XL))?$`

Wait, but I need to be careful about non-ASCII. In Python, `[A-Z]` in a regex with a string (not bytes) should only match ASCII A-Z by default. Let me verify... Actually in Python 3, `[A-Z]` matches exactly the characters A through Z, which are ASCII. So that should be fine.

But wait - what about characters that look like uppercase but aren't ASCII? Like 'Å' or something? In Python 3, `[A-Z]` in a regex only matches the literal characters A-Z (ASCII 65-90), so non-ASCII uppercase letters won't match. Good.

Similarly `[0-9]` only matches ASCII digits 0-9.

Let me write the function:

```python
import re

def parse_sku(code: str) -> dict:
    if not isinstance(code, str):
        raise ValueError("Input must be a string")
    
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

Wait, I need to think about whether `re.match` with `$` at the end is sufficient. `re.match` anchors at the start, and `$` anchors at the end. But `$` in Python can also match before a trailing newline. Let me use `\Z` instead to be strict.

Actually, let me reconsider. The spec says "Ignore leading and trailing whitespace." So I strip whitespace first. Then the pattern should match the entire string. Using `^...$` with `re.match` should work, but to be extra safe against the newline issue, I'll use `\Z` instead of `$`.

Actually, since I'm stripping whitespace first, a trailing newline would be stripped. So `$` should be fine. But let me use `\Z` to be absolutely safe.

Wait, actually `str.strip()` removes all whitespace including newlines, so after stripping, there won't be a trailing newline. So `$` is fine. But `\Z` is still safer as a practice.

Let me also consider: what if the input is not a string? The type hint says `str`, but should I validate? The problem says "Anything else... must raise ValueError." I think I'll add a type check.

Actually, re-reading the problem: "Anything else — lowercase, wrong lengths, unknown sizes, extra parts, non-ASCII characters — must raise ValueError." This seems to be about the content of the string, not about the type. I'll keep it simple and just handle the string case.

Let me also think about: what if there's a dash in the middle that creates an empty part? Like "HH--12345" or "HH-ABC--12345"? The regex won't match these because `[A-Z]{3}` requires exactly 3 letters and `[0-9]{5}` requires exactly 5 digits.

What about "HH-ABC-12345-"? The regex won't match because after the number, it expects either end of string or `-SIZE`. A trailing dash with nothing after won't match.

I think the regex approach is clean and handles all cases. Let me finalize.

One more thought: should I use `re.fullmatch` instead of `re.match` with `^...$`? `re.fullmatch` is cleaner and avoids the `$` vs `\Z` issue. Let me use that.

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

This is clean and handles all the cases. Let me verify:
- "HH-ABC-12345" → matches, size is None ✓
- "HH-ABC-12345-S" → matches, size is "S" ✓
- "HH-ABC-12345-XL" → matches, size is "XL" ✓
- "HH-abc-12345" → no match (lowercase) ✓
- "HH-AB-12345" → no match (2 letters) ✓
- "HH-ABCD-12345" → no match (4 letters) ✓
- "HH-ABC-1234" → no match (4 digits) ✓
- "HH-ABC-123456" → no match (6 digits) ✓
- "HH-ABC-12345-X" → no match (unknown size) ✓
- "HH-ABC-12345-S-M" → no match (extra part) ✓
- "HH-ABC-12345-" → no match (trailing dash) ✓
- "HH-ABC-12345-s" → no match (lowercase size) ✓
- "  HH-ABC-12345  " → stripped, matches ✓
- "HH-ABC-01234" → matches, number is "01234" (leading zeros preserved) ✓

Looks good!
