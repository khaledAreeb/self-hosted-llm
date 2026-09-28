"""
Measure decode throughput against the deployed endpoint.

    set -a; . ./.env; set +a
    python3 eval/decode_bench.py 3          # 1 warmup + 3 measured runs

Uses streaming so time-to-first-token can be separated from generation time.
Decode rate is (completion_tokens - 1) / (total - ttft): the first token is
excluded because it arrives at TTFT, not during generation.

Completion tokens include reasoning tokens. That is deliberate -- decode speed
is decode speed regardless of which field a token lands in -- but it means
results are only comparable between runs with the same thinking setting.
"""

import json
import os
import sys
import time
import urllib.request

URL = "https://dev-khaled-areeb--qwen38-27b-serve.modal.run/v1/chat/completions"
MODEL = "Qwen/Qwen3.8-27B-FP8"
PROMPT = "Write a detailed 300-word explanation of how warehouse cycle counting works."
MAX_TOKENS = 1200


def run_once():
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
    ).encode()
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
    usage = None
    with urllib.request.urlopen(req, timeout=1500) as resp:
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
                # vLLM streams thinking as "reasoning"; LiteLLM renames it
                # "reasoning_content". Either counts as the first token.
                if ttft is None and any(
                    delta.get(k) for k in ("content", "reasoning", "reasoning_content")
                ):
                    ttft = time.time() - start
    total = time.time() - start

    tokens = usage["completion_tokens"]
    details = usage.get("completion_tokens_details") or {}
    decode = (tokens - 1) / (total - ttft) if ttft and total > ttft else float("nan")
    return {
        "ttft_s": round(ttft, 3),
        "total_s": round(total, 2),
        "completion_tokens": tokens,
        "reasoning_tokens": details.get("reasoning_tokens"),
        "decode_tok_s": round(decode, 1),
    }


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print("warmup:", json.dumps(run_once()))
    results = [run_once() for _ in range(runs)]
    for r in results:
        print("run:   ", json.dumps(r))
    rates = [r["decode_tok_s"] for r in results]
    print(
        "summary:",
        json.dumps(
            {
                "runs": runs,
                "decode_tok_s_mean": round(sum(rates) / runs, 1),
                "min": min(rates),
                "max": max(rates),
                "spread": round(max(rates) - min(rates), 1),
            }
        ),
    )
