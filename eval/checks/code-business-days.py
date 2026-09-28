import sys
from datetime import date

from _common import answer_code, report

ns = {}
exec(answer_code(sys.argv[1], ["python", "py"], "def business_days"), ns)
business_days = ns["business_days"]
failures = []

cases = [
    # 2025-09-28 is a Sunday. Sun..Thu are working days; Fri and Sat are the weekend.
    ("one full week", (date(2025, 9, 28), date(2025, 10, 5)), {}, 5),
    ("end is exclusive", (date(2025, 9, 28), date(2025, 9, 29)), {}, 1),
    ("same day", (date(2025, 9, 28), date(2025, 9, 28)), {}, 0),
    ("end before start", (date(2025, 10, 5), date(2025, 9, 28)), {}, 0),
    ("weekend only", (date(2025, 10, 3), date(2025, 10, 5)), {}, 0),
    ("holiday excluded", (date(2025, 10, 5), date(2025, 10, 8)), {"holidays": {date(2025, 10, 6)}}, 2),
    ("holiday as list", (date(2025, 10, 5), date(2025, 10, 8)), {"holidays": [date(2025, 10, 6)]}, 2),
    ("holiday on weekend", (date(2025, 9, 28), date(2025, 10, 5)), {"holidays": {date(2025, 10, 3)}}, 5),
    ("four weeks", (date(2025, 9, 28), date(2025, 10, 26)), {}, 20),
]
for name, args, kwargs, want in cases:
    try:
        got = business_days(*args, **kwargs)
    except Exception as e:
        failures.append(f"{name}: raised {e!r}")
        continue
    if got != want:
        failures.append(f"{name}: got {got}, want {want}")

# The original's mutable default must not leak state between calls.
business_days(date(2025, 10, 5), date(2025, 10, 8), holidays={date(2025, 10, 6)})
if business_days(date(2025, 10, 5), date(2025, 10, 8)) != 3:
    failures.append("holidays from an earlier call leaked into a later call")

report(failures)
