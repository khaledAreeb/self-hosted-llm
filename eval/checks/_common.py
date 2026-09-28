"""Shared helpers for the automated checks in this folder."""

import re
import sys


def answer_text(result_path):
    """The model's answer from a result file written by eval/run_eval.py."""
    text = open(result_path, encoding="utf-8").read()
    return text.split("\n## Answer\n", 1)[1].split("\n## Reasoning\n", 1)[0]


def answer_code(result_path, langs, needle):
    """First fenced code block in one of `langs` that contains `needle`."""
    pattern = rf"```(?:{'|'.join(langs)})[ \t]*\n(.*?)```"
    for block in re.findall(pattern, answer_text(result_path), flags=re.S | re.I):
        if needle in block:
            return block
    report([f"no ```{langs[0]} block containing {needle!r} in the answer"])


def report(failures):
    for f in failures:
        print("  FAIL", f)
    print("PASS" if not failures else f"FAILED {len(failures)} check(s)")
    sys.exit(1 if failures else 0)
