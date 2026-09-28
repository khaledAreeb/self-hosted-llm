# code-sql-top-customers@medium (coding)

| metric | value |
|---|---|
| prompt_tokens | 228 |
| completion_tokens | 719 |
| reasoning_tokens | 595 |
| ttft_s | 0.85 |
| total_s | 6.32 |
| finish_reason | stop |
| answer_words | 54 |
| empty_answer | False |
| truncated | False |

attach: `none`  max_tokens: 16000

## Prompt

SQLite schema:

    CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT);
    CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
                         order_date TEXT,   -- 'YYYY-MM-DD'
                         status TEXT);      -- 'open', 'shipped' or 'cancelled'
    CREATE TABLE order_lines (id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id),
                              product_id INTEGER, qty INTEGER, unit_price REAL,
                              discount REAL);  -- fraction between 0 and 1

Write one SQLite query returning the top 5 customers by 2025 net revenue. Net revenue is `qty * unit_price * (1 - discount)` summed over the customer's orders dated in 2025, excluding cancelled orders. Columns, in order: `customer_name`, `order_count` (number of distinct qualifying orders), `net_revenue` rounded to 2 decimals. Sort by net_revenue descending. Reply with the query in a single sql code block.

## Good answer looks like (written before running)

Passes `eval/checks/code-sql-top-customers.py`, which compares the query's output against values computed independently in Python. Traps in the data: a huge cancelled order, large orders on 2024-12-31 and 2026-01-01, and multi-line orders. `COUNT(*)` instead of `COUNT(DISTINCT o.id)` inflates order_count roughly threefold.

## Answer

```sql
SELECT
    c.name AS customer_name,
    COUNT(DISTINCT o.id) AS order_count,
    ROUND(SUM(ol.qty * ol.unit_price * (1 - ol.discount)), 2) AS net_revenue
FROM customers c
JOIN orders o       ON o.customer_id = c.id
JOIN order_lines ol ON ol.order_id   = o.id
WHERE o.status != 'cancelled'
  AND o.order_date LIKE '2025-%'
GROUP BY c.id
ORDER BY net_revenue DESC
LIMIT 5;
```

## Reasoning

The user wants a SQLite query that:
1. Returns top 5 customers by 2025 net revenue
2. Net revenue = qty * unit_price * (1 - discount) summed over customer's orders dated in 2025
3. Excludes cancelled orders
4. Columns: customer_name, order_count (distinct qualifying orders), net_revenue (rounded to 2 decimals)
5. Sort by net_revenue descending
6. Limit to 5

Let me think about the joins:
- customers → orders (on customer_id)
- orders → order_lines (on order_id)

Filters:
- order_date in 2025: order_date LIKE '2025-%' or strftime('%Y', order_date) = '2025'
- status != 'cancelled'

Aggregations:
- customer_name: from customers
- order_count: COUNT(DISTINCT o.id) - distinct qualifying orders
- net_revenue: ROUND(SUM(ol.qty * ol.unit_price * (1 - ol.discount)), 2)

Group by customer.

Let me write this:

```sql
SELECT 
    c.name AS customer_name,
    COUNT(DISTINCT o.id) AS order_count,
    ROUND(SUM(ol.qty * ol.unit_price * (1 - ol.discount)), 2) AS net_revenue
FROM customers c
JOIN orders o ON o.customer_id = c.id
JOIN order_lines ol ON ol.order_id = o.id
WHERE o.status != 'cancelled'
  AND o.order_date LIKE '2025-%'
GROUP BY c.id
ORDER BY net_revenue DESC
LIMIT 5;
```

Wait, should I use `o.order_date LIKE '2025-%'` or `strftime('%Y', o.order_date) = '2025'`? Since the format is 'YYYY-MM-DD', `LIKE '2025-%'` is simpler and more efficient. Both work. I'll go with `LIKE '2025-%'`.

Also, should I consider that discount could be NULL? The schema says `discount REAL` without NOT NULL, so it could be NULL. But the problem says "fraction between 0 and 1" so I'll assume it's always present. If I want to be safe, I could use COALESCE(ol.discount, 0), but the problem statement implies it's always there. I'll keep it simple.

Let me also consider: should I use `c.id` in GROUP BY or `c.name`? Using `c.id` is safer since names could theoretically be duplicated. But the problem asks for customer_name in the output. I'll group by c.id and select c.name.

This looks correct. Let me finalize.
