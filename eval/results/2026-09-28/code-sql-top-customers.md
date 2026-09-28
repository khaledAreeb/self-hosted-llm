# code-sql-top-customers (coding)

| metric | value |
|---|---|
| prompt_tokens | 258 |
| completion_tokens | 602 |
| reasoning_tokens | 456 |
| ttft_s | 0.8 |
| total_s | 5.24 |
| finish_reason | stop |
| answer_words | 58 |
| empty_answer | False |
| truncated | False |

attach: `none`  max_tokens: 4000

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
JOIN orders o ON o.customer_id = c.id
JOIN order_lines ol ON ol.order_id = o.id
WHERE o.order_date >= '2025-01-01'
  AND o.order_date < '2026-01-01'
  AND o.status != 'cancelled'
GROUP BY c.id
ORDER BY net_revenue DESC
LIMIT 5;
```

## Reasoning

Let me break down the requirements:

1. Top 5 customers by 2025 net revenue
2. Net revenue = SUM(qty * unit_price * (1 - discount))
3. Orders dated in 2025 (order_date between '2025-01-01' and '2025-12-31')
4. Exclude cancelled orders (status != 'cancelled')
5. Columns: customer_name, order_count (distinct qualifying orders), net_revenue (rounded to 2 decimals)
6. Sort by net_revenue descending
7. Limit to 5

I need to join customers → orders → order_lines, filter by date and status, group by customer, and order by net revenue.

Let me write this:

```sql
SELECT 
    c.name AS customer_name,
    COUNT(DISTINCT o.id) AS order_count,
    ROUND(SUM(ol.qty * ol.unit_price * (1 - ol.discount)), 2) AS net_revenue
FROM customers c
JOIN orders o ON o.customer_id = c.id
JOIN order_lines ol ON ol.order_id = o.id
WHERE o.order_date >= '2025-01-01' AND o.order_date < '2026-01-01'
  AND o.status != 'cancelled'
GROUP BY c.id
ORDER BY net_revenue DESC
LIMIT 5;
```

This should work. Using `>= '2025-01-01' AND < '2026-01-01'` is the standard way to handle date ranges with TEXT dates in 'YYYY-MM-DD' format since lexicographic ordering works correctly.

I could also use `strftime('%Y', o.order_date) = '2025'` but the range comparison is more efficient and equally correct.

Let me also consider: should I use `c.id` or `c.name` in GROUP BY? Using `c.id` is safer since it's the primary key and unique. I'll group by `c.id` and select `c.name`.
