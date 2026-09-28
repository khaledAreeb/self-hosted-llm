import json
import re
import sys

from _common import answer_text, report

text = answer_text(sys.argv[1])
m = re.search(r"```(?:json)?\s*\n(.*?)```", text, flags=re.S) or re.search(r"(\{.*\})", text, flags=re.S)
try:
    got = json.loads(m.group(1))
except Exception as e:
    report([f"answer is not parseable JSON: {e}"])

failures = []


def num(v):
    return float(str(v).replace(",", ""))


for key, want in [("invoice_number", "RSP-2025-08817"), ("invoice_date", "2025-09-03"),
                  ("due_date", "2025-10-03"), ("po_reference", "PO-45120")]:
    if str(got.get(key, "")).strip() != want:
        failures.append(f"{key}: {got.get(key)!r}, want {want!r}")
if "red sea packaging" not in str(got.get("supplier", "")).lower():
    failures.append(f"supplier: {got.get('supplier')!r}")
for key, want in [("subtotal", 37930.00), ("vat", 5310.20), ("total", 43240.20)]:
    try:
        if abs(num(got.get(key)) - want) > 0.005:
            failures.append(f"{key}: {got.get(key)!r}, want {want}")
    except (TypeError, ValueError):
        failures.append(f"{key}: {got.get(key)!r} is not a number")

want_lines = [("CB-4030", 1200, 6.75, 8100.00), ("SF-23500", 85, 214.00, 18190.00),
              ("PL-A5", 5000, 0.42, 2100.00), ("PT-48", 360, 18.50, 6660.00),
              ("EP-100", 900, 3.20, 2880.00)]
lines = got.get("line_items") or []
if len(lines) != len(want_lines):
    failures.append(f"{len(lines)} line items, want {len(want_lines)}")
for i, (line, (code, qty, price, amount)) in enumerate(zip(lines, want_lines), 1):
    try:
        if line.get("code") != code or num(line.get("qty")) != qty or \
                abs(num(line.get("unit_price")) - price) > 0.005 or abs(num(line.get("amount")) - amount) > 0.005:
            failures.append(f"line {i}: {line!r}, want {code} {qty} x {price} = {amount}")
    except (AttributeError, TypeError, ValueError):
        failures.append(f"line {i}: malformed {line!r}")
report(failures)
