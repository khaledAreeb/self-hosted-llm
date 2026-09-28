import copy
import sys

from _common import answer_code, report

ns = {}
exec(answer_code(sys.argv[1], ["python", "py"], "def abc_classify"), ns)
abc_classify = ns["abc_classify"]
failures = []

cases = [
    ("empty", [], {}),
    ("basic", [("A1", 500), ("B2", 300), ("C3", 120), ("D4", 50), ("E5", 30)],
     {"A1": "A", "B2": "A", "C3": "B", "D4": "B", "E5": "C"}),
    # Tie on value: sku ascending decides the order, and here it decides the class.
    ("tie-break", [("K", 790), ("B", 100), ("A", 100), ("Q", 10)],
     {"K": "A", "A": "A", "B": "B", "Q": "C"}),
    ("zero total", [("A", 0), ("B", 0)], {"A": "C", "B": "C"}),
    ("single item", [("ONLY", 42)], {"ONLY": "A"}),
]
for name, items, want in cases:
    before = copy.deepcopy(items)
    try:
        got = abc_classify(items)
    except Exception as e:
        failures.append(f"{name}: raised {e!r}")
        continue
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
    if items != before:
        failures.append(f"{name}: input list was modified")

report(failures)
