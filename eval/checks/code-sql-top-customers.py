import random
import sqlite3
import sys

from _common import answer_code, report

SCHEMA = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
                     order_date TEXT, status TEXT);
CREATE TABLE order_lines (id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id),
                          product_id INTEGER, qty INTEGER, unit_price REAL, discount REAL);
"""


def build():
    rng = random.Random(7)
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    names = ["Nile Mart", "Delta Hypermarket", "Sokhna Foods", "Cairo Corner", "Giza Grocers",
             "Alex Retail", "Sinai Stores", "Luxor Fresh", "Tanta Trading", "Aswan Market",
             "Obour Wholesale", "Canal Supplies"]
    for i, n in enumerate(names, 1):
        db.execute("INSERT INTO customers VALUES (?, ?, ?)", (i, n, "Cairo"))
    oid = lid = 0

    def order(cust, day, status, lines):
        nonlocal oid, lid
        oid += 1
        db.execute("INSERT INTO orders VALUES (?, ?, ?, ?)", (oid, cust, day, status))
        for qty, price, disc in lines:
            lid += 1
            db.execute("INSERT INTO order_lines VALUES (?, ?, ?, ?, ?, ?)",
                       (lid, oid, rng.randint(1, 500), qty, price, disc))

    for _ in range(320):
        cust = rng.randint(1, len(names))
        day = f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        status = rng.choice(["shipped"] * 8 + ["open"] + ["cancelled"])
        lines = [(rng.randint(1, 40), round(rng.uniform(5, 400), 2), rng.choice([0, 0, 0.05, 0.1]))
                 for _ in range(rng.randint(1, 5))]
        order(cust, day, status, lines)
    # Traps: a huge cancelled order, and big orders just outside 2025.
    order(12, "2025-06-15", "cancelled", [(500, 400.0, 0)])
    order(11, "2024-12-31", "shipped", [(400, 390.0, 0)])
    order(10, "2026-01-01", "shipped", [(400, 390.0, 0)])
    order(9, "2025-12-31", "shipped", [(3, 100.0, 0.5)])  # inside 2025, small
    return db


def expected(db):
    """Computed in Python, independently of any SQL."""
    names = dict(db.execute("SELECT id, name FROM customers"))
    orders = {o: (c, d, s) for o, c, d, s in db.execute("SELECT * FROM orders")}
    revenue, counted = {}, {}
    for _, o, _, qty, price, disc in db.execute("SELECT * FROM order_lines"):
        c, d, s = orders[o]
        if d.startswith("2025-") and s != "cancelled":
            revenue[c] = revenue.get(c, 0) + qty * price * (1 - disc)
            counted.setdefault(c, set()).add(o)
    ranked = sorted(revenue, key=lambda c: -revenue[c])
    gap = (revenue[ranked[4]] - revenue[ranked[5]]) / revenue[ranked[4]]
    assert gap > 0.01, "fixture has a near-tie at rank 5; change the seed"
    return [(names[c], len(counted[c]), round(revenue[c], 2)) for c in ranked[:5]]


db = build()
want = expected(db)
sql = answer_code(sys.argv[1], ["sql", "sqlite"], "SELECT")
try:
    got = [tuple(r) for r in db.execute(sql).fetchall()]
except Exception as e:
    report([f"query failed: {e}"])

failures = []
if len(got) != 5:
    failures.append(f"returned {len(got)} rows, want 5")
for i, (g, w) in enumerate(zip(got, want), 1):
    if len(g) != 3:
        failures.append(f"row {i}: {len(g)} columns, want 3")
        continue
    if g[0] != w[0]:
        failures.append(f"row {i}: customer {g[0]!r}, want {w[0]!r}")
    if g[1] != w[1]:
        failures.append(f"row {i}: order_count {g[1]}, want {w[1]}")
    if abs(float(g[2]) - w[2]) > 0.01:
        failures.append(f"row {i}: net_revenue {g[2]}, want {w[2]}")
report(failures)
