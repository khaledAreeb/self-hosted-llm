import sys

from _common import answer_code, report

ns = {}
exec(answer_code(sys.argv[1], ["python", "py"], "def parse_sku"), ns)
parse_sku = ns["parse_sku"]
failures = []

good = {
    "HH-DRY-10231": {"category": "DRY", "number": "10231", "size": None},
    "HH-TEX-00042-XL": {"category": "TEX", "number": "00042", "size": "XL"},
    "  HH-COL-55555-M \n": {"category": "COL", "number": "55555", "size": "M"},
    "HH-ABC-99999-S": {"category": "ABC", "number": "99999", "size": "S"},
    "HH-ABC-12345-L": {"category": "ABC", "number": "12345", "size": "L"},
}
for code, want in good.items():
    try:
        got = parse_sku(code)
    except Exception as e:
        failures.append(f"{code!r} raised {e!r}")
        continue
    if got != want:
        failures.append(f"{code!r} -> {got!r}, want {want!r}")

bad = [
    "hh-DRY-10231", "HH-DR-10231", "HH-DRYX-10231", "HH-DRY-1023", "HH-DRY-102311",
    "HH-DRY-10231-XXL", "HH-DRY-10231-M-X", "HH-dry-10231", "", "XX-DRY-10231",
    "HH-DRY-10231-", "HH-DRY-1O231", "HH-D1Y-10231", "HH-DRY-10231-m", "HH DRY 10231",
    "HH-DRY-١٠٢٣١",  # Arabic-Indic digits: \d matches them
    "HH-ÄBC-10231",                      # non-ASCII uppercase: str.isupper() accepts it
]
for code in bad:
    try:
        got = parse_sku(code)
    except ValueError:
        continue
    except Exception as e:
        failures.append(f"{code!r} raised {type(e).__name__}, want ValueError")
        continue
    failures.append(f"{code!r} accepted -> {got!r}, want ValueError")

report(failures)
