"""
Build the load-test datasets from the phase 2 evaluation set.

    python3 bench/make_datasets.py

Writes bench/datasets/interactive.json: the 12 coding and report prompts from
eval/tasks.md, one {"prompt": ...} record each, cycled 20 times (240 records).
The cycling is only because GuideLLM stops a run when its dataset runs out, and
the busiest level needs ~113 requests; there are still just 12 unique prompts.

Real prompts, not synthetic text, because they produce real thinking lengths,
and time to first visible token depends on thinking length.

No output length is stored on purpose. GuideLLM turns an output-length column
into max_tokens plus ignore_eos, which forces every answer to the same length;
without it the model stops naturally and run.sh sets only a max_tokens cap.

Also writes bench/datasets/validate.json: eval/decode_bench.py's single prompt,
so GuideLLM can be checked against that script on identical work (task 3.4).

The agent workload is synthetic (a shared 16K-token prefix) and needs no file;
see run.sh.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "eval"))
from run_eval import parse_tasks  # noqa: E402  (the same parser the eval uses)
from decode_bench import PROMPT as DECODE_PROMPT  # noqa: E402

OUT = os.path.join(HERE, "datasets", "interactive.json")
CYCLES = 20


def main():
    tasks = [t for t in parse_tasks() if t["area"] in ("coding", "report")]
    records = [{"prompt": t["prompt"]} for _ in range(CYCLES) for t in tasks]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=1, ensure_ascii=False)
    print(f"wrote {len(records)} records ({len(tasks)} unique prompts x {CYCLES}) to {OUT}")
    for t in tasks:
        print(f"  {t['id']}")
    validate = os.path.join(os.path.dirname(OUT), "validate.json")
    with open(validate, "w", encoding="utf-8") as f:
        json.dump([{"prompt": DECODE_PROMPT}] * 40, f, indent=1)
    print(f"wrote 40 copies of the decode_bench prompt to {validate}")


if __name__ == "__main__":
    main()
