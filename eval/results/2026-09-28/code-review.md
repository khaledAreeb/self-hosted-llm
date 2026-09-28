# code-review (coding)

| metric | value |
|---|---|
| prompt_tokens | 303 |
| completion_tokens | 1797 |
| reasoning_tokens | 1088 |
| ttft_s | 0.9 |
| total_s | 15.92 |
| finish_reason | stop |
| answer_words | 384 |
| empty_answer | False |
| truncated | False |

attach: `none`  max_tokens: 5000

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

## Problems (most severe first)

| # | Problem | Reason |
|---|---------|--------|
| 1 | **SQL injection** via f-string interpolation of `customer_name` | An attacker can supply input like `'; DROP TABLE customers; --` to execute arbitrary SQL. |
| 2 | **No guard for missing customer** — `row` can be `None` | `row[0]` raises `TypeError` and crashes the function when the customer doesn't exist. |
| 3 | **Mutable default argument** `cache={}` | The dict is created once and shared across *all* calls, returning stale data and making the function stateful in a surprising way. |
| 4 | **Connection is never closed** | Leaks a file descriptor / DB handle on every call; will exhaust resources under load. |
| 5 | **Bare `except: pass`** | Silently swallows *every* exception (including `KeyboardInterrupt` in Py2, and all real errors in Py3), making failures invisible. |
| 6 | **N+1 query pattern** | One query per order to fetch lines; degrades linearly with order count. |
| 7 | **Not thread-safe** | The shared mutable cache (and even the local `orders` list if caching were kept) has no locking. |

## Corrected version

```python
import sqlite3
import json


def export_customer_orders(db_path: str, customer_name: str, out_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        cur.execute("SELECT id FROM customers WHERE name = ?", (customer_name,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Customer '{customer_name}' not found")
        customer_id = row[0]

        cur.execute(
            """
            SELECT o.id, ol.qty, ol.unit_price
            FROM orders o
            JOIN order_lines ol ON ol.order_id = o.id
            WHERE o.customer_id = ?
            """,
            (customer_id,),
        )

        totals: dict[int, float] = {}
        for order_id, qty, price in cur.fetchall():
            totals[order_id] = totals.get(order_id, 0) + qty * price

        orders = [{"order_id": oid, "total": total} for oid, total in totals.items()]

        with open(out_path, "w") as f:
            json.dump(orders, f)

        return orders
    finally:
        conn.close()
```

### Key changes

- **Parameterised queries** (`?` placeholders) eliminate SQL injection.
- **Explicit `None` check** with a descriptive `ValueError`.
- **Cache removed** — if you need it, use a proper `functools.lru_cache` or a module-level dict guarded by a lock, with an explicit invalidation strategy.
- **`try/finally`** guarantees the connection is closed even on exceptions.
- **`with open(...)`** replaces the manual open/write and the bare `except`; I/O errors now propagate to the caller.
- **Single JOIN query** replaces the N+1 loop.

## Reasoning

Let me analyze this function carefully for production-readiness issues.

1. **SQL Injection** - The function uses f-strings to interpolate `customer_name` directly into SQL queries. This is a critical security vulnerability. An attacker could pass a malicious `customer_name` to execute arbitrary SQL.

2. **Mutable default argument** - `cache={}` is a classic Python bug. The dictionary persists across function calls, meaning the cache is shared across all invocations. This is likely unintended behavior and can cause stale data to be returned.

3. **No error handling for missing customer** - If `row` is `None` (customer not found), `row[0]` will raise a `TypeError`. There's no check for this case.

4. **Bare except with pass** - The `except: pass` swallows all exceptions silently. If the file write fails (permissions, disk full, etc.), the caller has no idea. This makes debugging extremely difficult.

5. **Connection never closed** - The `sqlite3` connection is never closed. This is a resource leak. In production, this will eventually exhaust file descriptors or connections.

6. **N+1 query problem** - For each order, a separate query is made to fetch order lines. This is inefficient but more of a performance issue than a correctness issue.

7. **Cache is not thread-safe** - If this is used in a multi-threaded environment, the cache dictionary could have race conditions.

8. **No input validation** - `customer_name` could be None or non-string, which would cause issues.

Let me order by severity:

1. SQL Injection (critical security)
2. No handling for missing customer (crash - TypeError on None)
3. Mutable default argument (correctness bug - stale cache across calls)
4. Connection never closed (resource leak)
5. Bare except with pass (swallows errors silently)
6. N+1 queries (performance)
7. Not thread-safe (concurrency issue)

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
            json.dump(orders, f)
        
        return orders
    finally:
        conn.close()
```

Wait, should I keep the cache? The mutable default is a bug, but maybe the intent was to have a cache. I'll remove it since it's buggy as written and the user asked me to fix problems. If they want caching, they should implement it properly (e.g., with a class or a module-level dict with proper locking). I'll mention it in the problems list.

Actually, let me reconsider the N+1 query. I could use a single query with JOIN to get all order lines at once. Let me do that for the corrected version.

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
        
        cur.execute("""
            SELECT o.id, ol.qty, ol.unit_price
            FROM orders o
            JOIN order_lines ol ON ol.order_id = o.id
            WHERE o.customer_id = ?
        """, (customer_id,))
        
        orders_by_id = {}
        for order_id, qty, price in cur.fetchall():
            if order_id not in orders_by_id:
                orders_by_id[order_id] = 0
            orders_by_id[order_id] += qty * price
        
        orders = [{"order_id": oid, "total": total} for oid, total in orders_by_id.items()]
        
        with open(out_path, "w") as f:
            json.dump(orders, f)
        
        return orders
    finally:
        conn.close()
```

This is cleaner. Let me finalize my answer.
