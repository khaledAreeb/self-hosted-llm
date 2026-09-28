# code-review@medium (coding)

| metric | value |
|---|---|
| prompt_tokens | 273 |
| completion_tokens | 2330 |
| reasoning_tokens | 1458 |
| ttft_s | 0.89 |
| total_s | 21.47 |
| finish_reason | stop |
| answer_words | 464 |
| empty_answer | False |
| truncated | False |

attach: `none`  max_tokens: 20000

## Prompt

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

## Good answer looks like (written before running)

Seven planted problems. A good answer finds at least 5 of them, ranks SQL injection first, and invents none:
1. SQL injection via the f-string holding `customer_name`. Critical, and must be ranked first.
2. `row` is `None` for an unknown customer, so `row[0]` raises `TypeError`.
3. The bare `except: pass` swallows write failures, so data is silently lost.
4. The file is never closed (no `with`), so output may not be flushed.
5. The connection is never closed.
6. The mutable default `cache={}` is shared across calls and never invalidated. A cache hit also skips writing to a *new* `out_path`.
7. N+1 queries (one per order); a JOIN with GROUP BY does it in one.

The corrected version uses parameterised queries and `with` blocks, and handles a missing customer. Money stored as float is a fair minor point.

## Answer

## Problems (most → least severe)

1. **SQL injection (critical):** `customer_name` is interpolated via f-string directly into SQL; an attacker can execute arbitrary statements.
2. **Uncaught `None` dereference (high):** If the customer doesn't exist, `row` is `None` and `row[0]` raises an unhandled `TypeError`.
3. **Bare `except: pass` (high):** Silently swallows *every* exception (permissions, disk full, `OSError`, …), so a failed write looks like success.
4. **Mutable default `cache={}` (high):** The dict is created once and shared across all calls—unbounded growth, not thread-safe, and the key ignores `db_path` so different databases collide.
5. **Connection never closed (medium):** No `try/finally` or context manager; any exception mid-function leaks the `sqlite3` connection.
6. **File handle not in a context manager (medium):** If `json.dumps` raises, the file is left open and unflushed.
7. **N+1 query pattern (medium):** One `SELECT` per order for line items; a single `JOIN … GROUP BY` would replace the loop.
8. **No input validation (low):** `db_path`, `out_path`, and `customer_name` are used without type or existence checks.

## Corrected version

```python
import sqlite3
import json
import os


def export_customer_orders(db_path: str, customer_name: str, out_path: str) -> list[dict]:
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")
    if not isinstance(customer_name, str) or not customer_name:
        raise ValueError("customer_name must be a non-empty string")

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        cur.execute("SELECT id FROM customers WHERE name = ?", (customer_name,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Customer '{customer_name}' not found")

        # Single JOIN replaces the per-order N+1 loop
        cur.execute(
            """
            SELECT o.id, COALESCE(SUM(ol.qty * ol.unit_price), 0)
            FROM   orders o
            LEFT JOIN order_lines ol ON ol.order_id = o.id
            WHERE  o.customer_id = ?
            GROUP BY o.id
            ORDER BY o.id
            """,
            (row[0],),
        )
        orders = [{"order_id": oid, "total": total} for oid, total in cur.fetchall()]

        with open(out_path, "w") as f:
            f.write(json.dumps(orders))

        return orders
    finally:
        conn.close()
```

### What changed and why

| Change | Reason |
|---|---|
| Parameterised queries (`?` placeholders) | Eliminates SQL injection |
| `if row is None: raise ValueError` | Graceful, explicit error for missing customer |
| Removed `cache` parameter | Broken mutable-default; if caching is truly needed, use a module-level `dict` keyed on `(db_path, customer_name)` with a TTL and a lock |
| `try / finally: conn.close()` | Guarantees the connection is released even on exception |
| `with open(…)` | File is always closed and flushed, even if `json.dumps` fails |
| Single `JOIN … GROUP BY` query | Replaces the N+1 loop; one round-trip to SQLite |
| `LEFT JOIN` + `COALESCE` | Orders with zero line items still appear (total 0) instead of vanishing |
| Input validation at the top | Fails fast with a clear message instead of a cryptic `sqlite3.OperationalError` |
| Removed bare `except: pass` | Errors now propagate to the caller, who can decide how to handle them |

## Reasoning

Let me analyze this function carefully for production-readiness issues, ordered by severity.

1. **SQL Injection** (CRITICAL): The function uses f-strings to interpolate `customer_name` directly into SQL queries. This is a classic SQL injection vulnerability. An attacker could pass a malicious `customer_name` to execute arbitrary SQL.

2. **Mutable default argument** (HIGH): `cache={}` is a mutable default argument. This means the cache persists across all calls to the function (it's shared), and worse, it's a well-known Python gotcha. But more critically for production, it means the cache is never cleared, grows unboundedly, and is shared across threads (not thread-safe).

3. **No error handling for missing customer** (HIGH): If `row` is `None` (customer not found), `row[0]` will raise a `TypeError`. There's no check.

4. **Bare except with pass** (HIGH): The `except: pass` swallows ALL exceptions silently. If the file can't be written (permissions, disk full, invalid path), the function silently succeeds and returns data as if everything worked. This makes debugging impossible and can mask critical failures.

5. **No connection cleanup / no context manager** (MEDIUM): The `sqlite3.connect()` is never closed. If an exception occurs mid-function, the connection leaks. Should use `with` statement or try/finally.

6. **N+1 query problem** (MEDIUM): For each order, a separate query is made to get order lines. This is inefficient for customers with many orders. Could be done with a JOIN.

7. **File not closed properly** (MEDIUM): `open(out_path, "w")` is not in a `with` block. If `json.dumps` raises an exception, the file handle leaks. Also, the file might not be flushed/closed properly.

8. **No input validation** (MEDIUM): No validation of `db_path`, `out_path`, or `customer_name` types.

9. **Cache is not thread-safe** (MEDIUM): If this is used in a multi-threaded environment, the dict cache has race conditions.

10. **The cache key is just customer_name** (LOW): If the same customer name exists for different databases, the cache would return stale data. The cache key should include `db_path`.

11. **No `conn.close()`** - already covered in #5.

12. **The `try/except` only wraps the file write, not the DB operations** - if DB operations fail, the connection isn't closed.

Let me reorder by severity:

1. SQL Injection (CRITICAL) - f-string in SQL
2. No null check on `row` (HIGH) - crashes if customer not found
3. Bare `except: pass` (HIGH) - swallows all errors silently
4. Mutable default argument `cache={}` (HIGH) - shared mutable state, unbounded growth, not thread-safe
5. No connection cleanup (MEDIUM) - resource leak on exception
6. File not in context manager (MEDIUM) - file handle leak
7. N+1 queries (MEDIUM) - performance
8. Cache key doesn't include db_path (LOW) - stale data across databases

Let me write the corrected version:

```python
import sqlite3
import json

def export_customer_orders(db_path, customer_name, out_path):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM customers WHERE name = ?", (customer_name,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Customer '{customer_name}' not found")
        
        customer_id = row[0]
        cur.execute("SELECT id FROM orders WHERE customer_id = ?", (customer_id,))
        order_ids = [r[0] for r in cur.fetchall()]
        
        orders = []
        for order_id in order_ids:
            cur.execute("SELECT qty, unit_price FROM order_lines WHERE order_id = ?", (order_id,))
            lines = cur.fetchall()
            total = sum(qty * price for qty, price in lines)
            orders.append({"order_id": order_id, "total": total})
        
        with open(out_path, "w") as f:
            f.write(json.dumps(orders))
        
        return orders
    finally:
        conn.close()
```

Wait, should I keep the cache? The mutable default is a bug, but maybe the intent was caching. I could use a module-level dict or a proper cache mechanism. But for a production function, I think removing the broken cache and noting it is better. Or I could implement it properly with a module-level dict. Let me think...

Actually, for a clean production version, I'll remove the broken cache (it was fundamentally broken with the mutable default) and note that if caching is needed, it should be implemented properly (e.g., with a module-level dict, proper keying, TTL, thread safety). I'll mention this in the problems list.

Let me also consider: should I use a JOIN to fix the N+1? For clarity and correctness, I'll keep the per-order query but note the N+1 issue. Actually, I can do it with a single query using a JOIN:

```sql
SELECT o.id, SUM(ol.qty * ol.unit_price) 
FROM orders o 
JOIN order_lines ol ON o.id = ol.order_id 
WHERE o.customer_id = ?
GROUP BY o.id
```

This is cleaner and more efficient. Let me use this.

Let me finalize my severity list (one line each):

1. CRITICAL: SQL injection via f-string interpolation of `customer_name` into queries.
2. HIGH: `row` is never checked for `None`; a missing customer causes an unhandled `TypeError` crash.
3. HIGH: Bare `except: pass` silently swallows every exception (permissions, disk full, etc.), making failures invisible.
4. HIGH: Mutable default `cache={}` is shared across all calls, grows unbounded, is not thread-safe, and is keyed only by name (ignores `db_path`).
5. MEDIUM: `sqlite3.connect()` is never closed; an exception mid-function leaks the connection.
6. MEDIUM: `open(out_path, "w")` is not in a `with` block; a failure in `json.dumps` leaks the file handle.
7. MEDIUM: N+1 query pattern — one query per order for line items; should be a single JOIN.
8. LOW: No input validation on `db_path`, `out_path`, or `customer_name` types.

That looks good. Let me write the final response.
