"""
Run the evaluation set in eval/tasks.md against the deployed endpoint.

    set -a; . ./.env; set +a
    python3 eval/run_eval.py                  # every task
    python3 eval/run_eval.py code-1 vision-2  # only these tasks
    python3 eval/run_eval.py --effort medium code-1   # re-run with more thinking

Tasks run one at a time so each latency is measured without interference.
Results go to eval/results/<today>/:

    <task-id>.md    the answer, the reasoning, and the "good answer" criteria
                    side by side, ready to be judged
    summary.json    per-task latency, token counts and finish reason
    deploy.py       copy of the serving config the results came from

Re-running a subset on the same day overwrites those tasks and keeps the rest.
With --effort, results are saved as <task-id>@<effort> so they sit beside the
default-effort result instead of replacing it.

Refuses to run a task that is still a FORMAT EXAMPLE, has no "good answer"
written, or points at an attachment that does not exist -- the criteria must
exist before the answer does, or it is a vibe check, not an evaluation.
"""

import base64
import datetime
import json
import mimetypes
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request

URL = "https://dev-khaled-areeb--qwen38-27b-serve.modal.run/v1/chat/completions"
MODEL = "Qwen/Qwen3.8-27B-FP8"
HERE = os.path.dirname(os.path.abspath(__file__))
TASKS_FILE = os.path.join(HERE, "tasks.md")
AREAS = {"coding", "report", "long-document", "vision"}


def section(block, name):
    """Text under '### <name>' up to the next heading or '---'."""
    m = re.search(
        rf"^### {re.escape(name)}\n(.*?)(?=^### |^---|^## |\Z)",
        block,
        flags=re.M | re.S,
    )
    return m.group(1).strip() if m else ""


def parse_tasks():
    text = open(TASKS_FILE).read()
    # The "Format" section shows a task inside a code fence; don't parse it.
    text = re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)
    tasks = []
    for block in re.split(r"^## TASK:\s*", text, flags=re.M)[1:]:
        task_id, _, rest = block.partition("\n")
        header = rest.split("### ")[0]
        fields = dict(re.findall(r"^- (\w+):\s*(.+?)\s*$", header, flags=re.M))
        tasks.append(
            {
                "id": task_id.strip(),
                "area": fields.get("area", ""),
                "max_tokens": int(fields.get("max_tokens", 2000)),
                "attach": fields.get("attach", "none"),
                "prompt": section(rest, "Prompt"),
                "good_answer": section(rest, "Good answer looks like"),
            }
        )
    return tasks


def problems(task):
    """Reasons this task must not run yet; empty list means it is ready."""
    found = []
    if "FORMAT EXAMPLE" in task["prompt"] + task["good_answer"]:
        found.append("still a FORMAT EXAMPLE")
    if task["area"] not in AREAS:
        found.append(f"area '{task['area']}' is not one of {sorted(AREAS)}")
    if not task["prompt"]:
        found.append("no prompt")
    if not task["good_answer"]:
        found.append("no 'good answer' written before running")
    if task["attach"] != "none":
        path = os.path.join(HERE, "..", task["attach"])
        if not os.path.isfile(path):
            found.append(f"attachment {task['attach']} not found")
    return found


def build_content(task):
    """The user message content: plain text, document + text, or image + text."""
    if task["attach"] == "none":
        return task["prompt"]
    path = os.path.join(HERE, "..", task["attach"])
    if task["area"] == "vision":
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        data = base64.b64encode(open(path, "rb").read()).decode()
        return [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
            {"type": "text", "text": task["prompt"]},
        ]
    # Document first, question last: the question is freshest when answering.
    return open(path, encoding="utf-8").read() + "\n\n---\n\n" + task["prompt"]


def run_task(task, effort):
    request = {
        "model": MODEL,
        "messages": [{"role": "user", "content": build_content(task)}],
        "max_tokens": task["max_tokens"],
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if effort:
        # Overrides the server default (CHAT_TEMPLATE_KWARGS in deploy.py).
        request["chat_template_kwargs"] = {"reasoning_effort": effort}
    body = json.dumps(request).encode()
    req = urllib.request.Request(
        URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {os.environ['MODAL_PROXY_TOKEN']}",
            "Content-Type": "application/json",
        },
    )

    start = time.time()
    ttft = None
    usage = {}
    finish = None
    answer, reasoning = [], []
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            for raw in resp:
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    finish = choice.get("finish_reason") or finish
                    # vLLM streams thinking as "reasoning"; LiteLLM renames
                    # it "reasoning_content".
                    think = delta.get("reasoning") or delta.get("reasoning_content")
                    if think:
                        reasoning.append(think)
                    if delta.get("content"):
                        answer.append(delta["content"])
                    if ttft is None and (think or delta.get("content")):
                        ttft = time.time() - start
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()[:500]}"}, "", ""
    except Exception as e:  # timeouts, dropped connections
        return {"error": f"{type(e).__name__}: {e}"}, "", ""
    total = time.time() - start

    answer, reasoning = "".join(answer), "".join(reasoning)
    details = usage.get("completion_tokens_details") or {}
    metrics = {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "ttft_s": round(ttft, 2) if ttft else None,
        "total_s": round(total, 2),
        "finish_reason": finish,
        "answer_words": len(answer.split()),
        # The failure modes seen so far: thinking ate the whole budget, or
        # the answer was cut off mid-sentence.
        "empty_answer": not answer.strip(),
        "truncated": finish == "length",
    }
    return metrics, answer, reasoning


def write_result(out_dir, name, task, metrics, answer, reasoning):
    lines = [
        f"# {name} ({task['area']})",
        "",
        "| metric | value |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in metrics.items()],
        "",
        f"attach: `{task['attach']}`  max_tokens: {task['max_tokens']}",
        "",
        "## Prompt",
        "",
        task["prompt"],
        "",
        "## Good answer looks like (written before running)",
        "",
        task["good_answer"],
        "",
        "## Answer",
        "",
        answer.strip() or "_(empty)_",
        "",
        "## Reasoning",
        "",
        reasoning.strip() or "_(none)_",
        "",
    ]
    with open(os.path.join(out_dir, f"{name}.md"), "w") as f:
        f.write("\n".join(lines))


def main():
    args = sys.argv[1:]
    effort = None
    if "--effort" in args:
        i = args.index("--effort")
        effort = args[i + 1]
        del args[i : i + 2]

    tasks = parse_tasks()
    wanted = args
    if wanted:
        unknown = set(wanted) - {t["id"] for t in tasks}
        if unknown:
            sys.exit(f"unknown task ids: {', '.join(sorted(unknown))}")
        tasks = [t for t in tasks if t["id"] in wanted]

    blocked = {t["id"]: problems(t) for t in tasks if problems(t)}
    for task_id, reasons in blocked.items():
        print(f"SKIP {task_id}: {'; '.join(reasons)}")
    tasks = [t for t in tasks if t["id"] not in blocked]
    if not tasks:
        sys.exit("nothing ready to run -- fill in eval/tasks.md first")

    out_dir = os.path.join(HERE, "results", datetime.date.today().isoformat())
    os.makedirs(out_dir, exist_ok=True)
    shutil.copy(os.path.join(HERE, "..", "deploy.py"), os.path.join(out_dir, "deploy.py"))
    summary_path = os.path.join(out_dir, "summary.json")
    summary = json.load(open(summary_path)) if os.path.exists(summary_path) else {}

    for i, task in enumerate(tasks, 1):
        name = f"{task['id']}@{effort}" if effort else task["id"]
        print(f"[{i}/{len(tasks)}] {name} ({task['area']}) ...", flush=True)
        metrics, answer, reasoning = run_task(task, effort)
        write_result(out_dir, name, task, metrics, answer, reasoning)
        summary[name] = {"area": task["area"], "effort": effort or "default", **metrics}
        # Saved after every task so an interrupted run keeps what it has.
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        print("   ", json.dumps(metrics), flush=True)

    print(f"\nresults in {out_dir}")


if __name__ == "__main__":
    main()
