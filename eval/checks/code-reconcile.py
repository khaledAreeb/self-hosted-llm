import copy
import sys

from _common import answer_code, report

ns = {}
exec(answer_code(sys.argv[1], ["python", "py"], "def reconcile"), ns)
reconcile = ns["reconcile"]
failures = []


def row(sku, ordered, received, issue):
    return {"sku": sku, "ordered": ordered, "received": received, "issue": issue}


cases = [
    ("all match", {"A": 5, "B": 3}, {"A": 5, "B": 3}, []),
    ("mixed",
     {"LD-1004": 480, "LD-1013": 1200, "LD-1021": 300, "LD-1041": 360},
     {"LD-1004": 480, "LD-1013": 1080, "LD-1021": 310, "LD-1007": 120},
     [row("LD-1007", 0, 120, "unexpected"), row("LD-1013", 1200, 1080, "short"),
      row("LD-1021", 300, 310, "over"), row("LD-1041", 360, 0, "missing")]),
    ("received zero counts as missing", {"X": 10}, {"X": 0}, [row("X", 10, 0, "missing")]),
    ("ordered zero is not on the order", {"Z": 0}, {"Z": 4}, [row("Z", 0, 4, "unexpected")]),
    ("nothing either side", {"Z": 0}, {"Y": 0}, []),
    ("empty", {}, {}, []),
]
for name, ordered, received, want in cases:
    o, r = copy.deepcopy(ordered), copy.deepcopy(received)
    try:
        got = reconcile(ordered, received)
    except Exception as e:
        failures.append(f"{name}: raised {e!r}")
        continue
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
    if ordered != o or received != r:
        failures.append(f"{name}: inputs were modified")

report(failures)
