# code-business-days@medium (coding)

| metric | value |
|---|---|
| prompt_tokens | 178 |
| completion_tokens | 1544 |
| reasoning_tokens | 1200 |
| ttft_s | 0.78 |
| total_s | 13.78 |
| finish_reason | stop |
| answer_words | 196 |
| empty_answer | False |
| truncated | False |

attach: `none`  max_tokens: 16000

## Prompt

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

## Good answer looks like (written before running)

Names three real bugs: (1) `<=` includes `end`, but the range is half-open `[start, end)`; (2) `(5, 6)` is Saturday/Sunday, but Friday/Saturday is `(4, 5)`; (3) `holidays` is never checked. Flagging the mutable default `set()` is good practice, but it is not a bug here since the set is never mutated. The fixed function passes `eval/checks/code-business-days.py`.

## Answer

## Bugs Found

1. **`while d <= end`** – The interval is `[start, end)` (end excluded), but `<=` includes `end` in the count.
2. **`d.weekday() not in (5, 6)`** – Python's `weekday()` maps Friday→4, Saturday→5; the code checks Saturday(5) and Sunday(6) instead.
3. **`holidays` is never consulted** – The parameter is accepted but the membership test is missing, so holiday dates are still counted as working days.
4. **`holidays=set()` mutable default** – A shared mutable default is a classic Python footgun; it should be `None` with an internal guard.

## Corrected Function

```python
from datetime import date, timedelta

def business_days(start: date, end: date, holidays=None) -> int:
    """Count working days in [start, end): our weekend is Friday and
    Saturday, and any date in `holidays` is also a day off.
    Returns 0 if end <= start."""
    if holidays is None:
        holidays = set()
    days = 0
    d = start
    while d < end:
        if d.weekday() not in (4, 5) and d not in holidays:
            days += 1
        d += timedelta(days=1)
    return days
```

The `while d < end` loop also naturally satisfies the "returns 0 if `end <= start`" contract, since the body never executes in that case.

## Reasoning

Let me analyze this function carefully to find all bugs.

The function is supposed to:
1. Count working days in [start, end) - half-open interval
2. Weekend is Friday and Saturday
3. Any date in `holidays` is also a day off
4. Returns 0 if end <= start

Let me check each aspect:

1. **Interval [start, end)**: The docstring says [start, end), meaning `end` should NOT be included. But the loop uses `while d <= end`, which includes `end`. It should be `while d < end`.

2. **Weekend is Friday and Saturday**: In Python's `date.weekday()`, Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6. So Friday is 4 and Saturday is 5. The code checks `d.weekday() not in (5, 6)` which is Saturday and Sunday. It should be `(4, 5)`.

3. **Holidays**: The function accepts a `holidays` parameter but never checks it. The condition should also exclude dates in `holidays`. The check should be something like `if d.weekday() not in (4, 5) and d not in holidays:`.

4. **Returns 0 if end <= start**: The function doesn't have an explicit check for this. However, if `end <= start`, the while loop `while d <= end` (or `while d < end` after fix) would not execute if `end < start`, but if `end == start`, with `while d < end` it wouldn't execute either. Wait, let me think again. If `end == start`, then `d = start`, and `d < end` is `start < start` which is False, so it returns 0. If `end < start`, then `d = start`, and `d < end` is False, so it returns 0. So actually with the corrected `while d < end`, the "Returns 0 if end <= start" is naturally handled. But wait - the original code with `while d <= end` would NOT return 0 if end == start (it would count one day). So the fix to `<` handles this case.

Actually, let me reconsider. The docstring says "Returns 0 if end <= start." With `while d < end`:
- If end < start: d = start, start < end is False → returns 0 ✓
- If end == start: d = start, start < end is False → returns 0 ✓

So the `<` fix handles this naturally. No separate check needed.

5. **Default mutable argument**: `holidays=set()` is a mutable default argument. This is a classic Python bug. It should be `holidays=None` and then `if holidays is None: holidays = set()` inside, or use a frozenset, or just document it. Actually, this is a well-known Python anti-pattern. Let me include this as a bug.

Wait, let me reconsider whether the mutable default is really a "bug" in the context of this problem. It's a code smell/anti-pattern that can lead to unexpected behavior if someone modifies the set. But in practice, if you just add elements to it, it would persist across calls. However, the function only reads from `holidays` (checks membership), so it wouldn't actually cause wrong answers in normal usage unless someone mutates the default set externally. I'll mention it but it's more of a style issue. Actually, the problem says "gives wrong answers" - the mutable default wouldn't give wrong answers unless someone mutates it. Let me focus on the bugs that actually give wrong answers.

Let me list the bugs that give wrong answers:
1. `while d <= end` should be `while d < end` (includes end in the count, but [start, end) excludes it)
2. `d.weekday() not in (5, 6)` should be `d.weekday() not in (4, 5)` (Friday=4, Saturday=5, not Saturday=5, Sunday=6)
3. `holidays` is never checked - dates in holidays should be excluded from the count

And the mutable default is a code quality issue but I'll mention it.

Let me write the corrected function:

```python
from datetime import date, timedelta

def business_days(start: date, end: date, holidays=None) -> int:
    """Count working days in [start, end): our weekend is Friday and
    Saturday, and any date in `holidays` is also a day off.
    Returns 0 if end <= start."""
    if holidays is None:
        holidays = set()
    days = 0
    d = start
    while d < end:
        if d.weekday() not in (4, 5) and d not in holidays:
            days += 1
        d += timedelta(days=1)
    return days
```

This handles all the bugs. The "Returns 0 if end <= start" is naturally handled by the `while d < end` condition.

Let me double-check:
- [start, end): `while d < end` ✓
- Weekend Friday(4) and Saturday(5): `d.weekday() not in (4, 5)` ✓
- Holidays excluded: `and d not in holidays` ✓
- Returns 0 if end <= start: naturally handled ✓
- Mutable default fixed: `holidays=None` with internal check ✓
