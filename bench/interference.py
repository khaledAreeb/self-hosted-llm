"""
Send one long-document request into a busy endpoint and record when it ran.

    bench/run.sh interactive 8 --label interference-8 --requests 60 &
    sleep 40; python3 bench/interference.py interference-8

The document is eval/docs/shipment-register-2025.txt (~137K tokens) with a
unique first line added, so the prefix cache cannot serve it from an earlier
read: this measures a genuinely fresh long document arriving among users.

Writes bench/results/<date>/<label>.overlap.json with the request's start/end
time and metrics. summarize.py uses the window to split that level's requests
into "overlapped the long read" and "did not".
"""

import json
import os
import sys
import time
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "eval"))
import run_eval  # noqa: E402  (same streaming client as the evaluation)

SOURCE = os.path.join(ROOT, "eval", "docs", "shipment-register-2025.txt")
QUESTION = next(t for t in run_eval.parse_tasks() if t["id"] == "longdoc-rejections")


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "interference-8"
    doc = os.path.join(ROOT, "eval", "docs", "interference-copy.txt")  # git-ignored folder
    with open(doc, "w", encoding="utf-8") as f:
        f.write(f"Interference test copy made at {time.time():.3f}\n")
        f.write(open(SOURCE, encoding="utf-8").read())
    task = {**QUESTION, "attach": os.path.relpath(doc, ROOT)}

    start = time.time()
    metrics, answer, _ = run_eval.run_task(task, None)
    end = time.time()
    os.remove(doc)

    out = os.path.join(HERE, "results", datetime.date.today().isoformat(), f"{label}.overlap.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    record = {"start": start, "end": end, "metrics": metrics,
              "found_all_4_rejections": all(i in answer for i in
                                            ("SHP-00141", "SHP-00952", "SHP-02221", "SHP-02748"))}
    json.dump(record, open(out, "w"), indent=2)
    print(json.dumps(record))


if __name__ == "__main__":
    main()
