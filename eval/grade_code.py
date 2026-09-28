"""
Run the automated checks in eval/checks/ against a results folder.

    python3 eval/grade_code.py                          # newest results folder
    python3 eval/grade_code.py eval/results/2026-09-28

Each eval/checks/<task-id>.py takes one result file, extracts the model's
code or JSON from the answer, and tests it. Results saved as <task-id>@<effort>
are checked too. Every check runs in its own process with a time limit,
because it executes code the model wrote.

Tasks without a check file (reports, long documents, most vision tasks) are
judged by reading the answer against its "good answer" criteria.
"""

import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    if len(sys.argv) > 1:
        results = sys.argv[1]
    else:
        folders = sorted(glob.glob(os.path.join(HERE, "results", "*")))
        if not folders:
            sys.exit("no results yet -- run eval/run_eval.py first")
        results = folders[-1]

    checks = sorted(glob.glob(os.path.join(HERE, "checks", "*.py")))
    for check in checks:
        task_id = os.path.basename(check)[:-3]
        if task_id.startswith("_"):
            continue
        files = sorted(glob.glob(os.path.join(results, f"{task_id}.md")) +
                       glob.glob(os.path.join(results, f"{task_id}@*.md")))
        if not files:
            print(f"{task_id}: no result")
            continue
        for path in files:
            name = os.path.basename(path)[:-3]
            try:
                run = subprocess.run([sys.executable, check, path], capture_output=True,
                                     text=True, timeout=60, cwd=os.path.dirname(check))
                out = (run.stdout + run.stderr).strip()
            except subprocess.TimeoutExpired:
                out = "FAILED: timed out after 60 s"
            print(f"{name}: {out.splitlines()[-1] if out else 'no output'}")
            for line in out.splitlines()[:-1]:
                print(f"    {line.strip()}")


if __name__ == "__main__":
    main()
