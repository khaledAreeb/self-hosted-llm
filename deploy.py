"""
Serve Qwen3.8-27B-FP8 on Modal with vLLM.

Two commands, in this order:

    modal run deploy.py::download     # run ONCE -- pulls ~28 GB into a Volume
    modal deploy deploy.py            # creates the authenticated endpoint

Then call it like any OpenAI-compatible API, with Modal's proxy-auth headers:

    curl https://<your-endpoint>/v1/chat/completions \
      -H "Modal-Key: wk-..." -H "Modal-Secret: ws-..." \
      -H "Content-Type: application/json" \
      -d '{"model":"Qwen/Qwen3.8-27B-FP8","messages":[{"role":"user","content":"hi"}]}'

Why this file is shaped the way it is -- GPU choice, FP8 over AWQ, the idle
window, edge auth -- is recorded in:
    openspec/changes/deploy-qwen38-27b-modal-pilot/design.md
"""

import subprocess

import modal

# ---------------------------------------------------------------------------
# Constants. Everything you would reasonably want to change lives here.
# ---------------------------------------------------------------------------

APP_NAME = "qwen38-27b"

# The publisher's official FP8 checkpoint. We deliberately do NOT quantize
# ourselves -- this build is near-lossless, already public under Apache-2.0,
# and avoids the Gated DeltaNet quantization traps that make custom INT4
# builds of this architecture risky.
MODEL_ID = "Qwen/Qwen3.8-27B-FP8"

# Weights are ~28.9 GiB, but the KV cache needs ~12.25 GiB MINIMUM, so the
# real requirement is ~42.4 GiB. A100-40GB was tried first and died with
# CUDA OOM during KV cache profiling -- it has only 39.49 GiB.
#
# The 12.25 GiB floor comes from this model's hybrid architecture. vLLM must
# make the attention page size match the Gated DeltaNet (mamba) state page
# size, which inflates the attention block to 1568 tokens instead of the
# usual 16. KV cache is cheap per TOKEN on this model but expensive per
# BLOCK, so even a minimal allocation is large.
#
# FP8-Marlin on Ampere was NOT the problem -- it worked, as logged:
#   "Weight-only FP8 compression will be used leveraging the Marlin kernel."
#
# L40S (48 GiB) also fits on paper, but at 0.90 utilization its budget is
# 43.2 GiB against a 42.4 GiB requirement -- only 0.8 GiB of margin.
# A100-80GB has ~29.6 GiB of margin and ~2x the memory bandwidth.
GPU = "A100-80GB"

# Native context is 262,144 tokens. Left at the default, vLLM reserves KV
# cache for all of it and strangles the GPU. 32K leaves ~9 GB of headroom on
# a 40 GB card -- roughly 160,000 tokens of KV budget, which is far more
# concurrent context than a small pilot team will use.
MAX_MODEL_LEN = 131_072

# Halves KV cache bytes per token (~64 KB -> ~32 KB at this model's shape).
KV_CACHE_DTYPE = "fp8"

# Turn OFF the model's chain-of-thought by default.
#
# This model ships with "xhigh" reasoning effort. Measured behaviour before
# this setting: a request for a 400-word explanation with max_tokens=800
# produced 800 reasoning tokens and ZERO visible content -- `content` came back
# as None with finish_reason="length". The model never began its answer. A
# streamed 150-word request behaved identically: 400 reasoning chunks, 0
# content chunks.
#
# Callers who genuinely want reasoning send it per request:
#     {"chat_template_kwargs": {"enable_thinking": true}}
# Request-level kwargs always take priority over this server default.
#
# Currently set to MEDIUM reasoning effort: thinking is on, but on a far
# smaller budget than the shipped default.
#
# Other values:
#   '{"enable_thinking": false}'        no reasoning at all, fastest
#   '{"reasoning_effort": "low"}'       minimal reasoning
#   '{"reasoning_effort": "medium"}'    current
#   (unset)                             "xhigh" -- the shipped default, which
#                                       measured 800 reasoning tokens and ZERO
#                                       visible content on a 400-word request
#
# With thinking on, callers must allow enough max_tokens for the reasoning
# AND the answer. Too small a budget and the model spends it all thinking,
# returning content: None with finish_reason "length".
CHAT_TEMPLATE_KWARGS = '{"reasoning_effort": "medium"}'

# Tool / function calling. Required by any agent-style client (GitHub Copilot's
# Agent mode, LangChain, etc.) -- they send tool definitions with
# tool_choice="auto", and without a parser vLLM rejects the request outright:
#     "auto" tool choice requires --enable-auto-tool-choice
#     and --tool-call-parser to be set
#
# The model is capable (81.27 on BFCL, a tool-calling benchmark); what was
# missing is the parser that turns its output into structured `tool_calls`.
# `qwen3_xml` is the value vLLM's published recipe for this model specifies.
#
# Caveat worth knowing: there are open vLLM issues where the qwen3 family of
# parsers mis-handles `tool_choice: "required"` and named-function choices.
# `auto` is the path that is actually exercised, so test any client that
# depends on the others.
TOOL_CALL_PARSER = "qwen3_xml"

GPU_MEMORY_UTILIZATION = 0.90

# Release the GPU after 5 minutes idle.
#
# Modal's own example ships 15 minutes. For a bursty team that is ~90 min/day
# of paid idle GPU -- about a third of the entire pilot budget, per day.
#
# Do NOT drop below ~2 minutes: a user who pauses 90 seconds to read an answer
# would otherwise trigger a cold start in the middle of their conversation.
IDLE_WINDOW_SECONDS = 10 * 60

# A 28 GB model takes minutes to load. Modal's default startup_timeout is 5
# SECONDS, which would kill the container while it is starting normally.
STARTUP_TIMEOUT_SECONDS = 15 * 60

# Per-request ceiling (not container lifetime). Generous enough for long
# generations, including reasoning traces.
REQUEST_TIMEOUT_SECONDS = 30 * 60

MAX_CONCURRENT_REQUESTS = 32

VLLM_PORT = 8000

# 0.17.0 is the minimum version supporting this model's hybrid architecture.
VLLM_VERSION = "0.17.0"

# Billed separately from the GPU on Modal (~$0.44/hr at these values, roughly
# 20% on top of the headline GPU price). Confirm against your first invoice.
CPU_CORES = 4
MEMORY_MB = 32 * 1024

# ---------------------------------------------------------------------------
# GPU memory snapshots were TRIED AND REVERTED on 2026-09-24. Do not retry
# without new evidence that Modal's implementation has changed.
#
# The idea was sound: of a 319 s cold start, vLLM reported that 220.92 s was
# "init engine (profile, create kv cache, warmup model)", which a snapshot
# should skip entirely. Implementing it required restructuring this file into
# a class with @modal.enter(snap=True/False) hooks, vLLM sleep mode, and
# raising memory to 64 GiB so level-1 sleep could offload 28.9 GiB of weights
# to CPU RAM.
#
# Five measured cold starts with snapshots enabled:
#     743 s, 580 s, 41 s, 784 s, 522 s     (median 580 s, mean 534 s)
# against a measured baseline of 319 s without them.
#
# One restore was genuinely fast (41 s, weights and KV cache woke in 3.6 s).
# The rest re-created the snapshot instead of restoring it, which costs more
# than a plain cold start. Modal's published 10x figure is for a 3B model;
# at 28.9 GiB the snapshot does not reliably stabilise, and the worst case
# (784 s) is far worse than the predictable 319 s it replaced.
#
# Unpredictable 41 s-to-13 min is worse for users than a reliable ~5 min, so
# the simpler function-based deployment below was restored. Cost of finding
# out: about $3.90.
# ---------------------------------------------------------------------------

# Volume mount points inside the container.
HF_CACHE_PATH = "/cache/huggingface"
VLLM_CACHE_PATH = "/cache/vllm"

# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------
# If the image fails to build, the CUDA tag below is the first thing to adjust.

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.8.1-devel-ubuntu22.04", add_python="3.12"
    )
    .pip_install(
        f"vllm>={VLLM_VERSION}",
        "huggingface_hub[hf_transfer]",
    )
    .env(
        {
            # Force the classic HTTP download path instead of Hugging Face's
            # Xet backend.
            #
            # This is not optional. With Xet enabled, `blobs/` is filled with
            # 79-byte symlinks pointing into a chunk cache that does not
            # survive the Volume commit -- the snapshot looks complete but the
            # weights are not actually there, so every cold start would
            # re-download 28 GB. Verified empirically on the first run:
            # 67 of 81 blobs were links, and only ~10 MB of real bytes landed.
            "HF_HUB_DISABLE_XET": "1",
            # Point both caches at the Volumes mounted below, so nothing is
            # re-downloaded or re-compiled on a cold start.
            "HF_HOME": HF_CACHE_PATH,
            "VLLM_CACHE_ROOT": VLLM_CACHE_PATH,
        }
    )
)

# ---------------------------------------------------------------------------
# Volumes
# ---------------------------------------------------------------------------
# Storage is free below 1 TiB, and these two together use ~33 GiB. Never
# delete them to save money -- it saves nothing and costs a 28 GB re-download.

hf_cache = modal.Volume.from_name("qwen38-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("qwen38-vllm-cache", create_if_missing=True)

VOLUMES = {HF_CACHE_PATH: hf_cache, VLLM_CACHE_PATH: vllm_cache}

app = modal.App(APP_NAME)


# ---------------------------------------------------------------------------
# Step 1: download the weights. Run this ONCE.
# ---------------------------------------------------------------------------
# Kept deliberately separate from serving. If the download happened on first
# boot instead, any cache miss would re-pull 28 GB and bill for the transfer.
# The serving path below only ever reads from the Volume.


@app.function(
    image=image,
    volumes=VOLUMES,
    cpu=CPU_CORES,
    memory=MEMORY_MB,
    timeout=60 * 60,
)
def download():
    from huggingface_hub import snapshot_download

    print(f"Downloading {MODEL_ID} into {HF_CACHE_PATH} ...")
    snapshot_download(MODEL_ID)
    hf_cache.commit()
    print("Done. Cold starts will now read from the Volume, not the network.")


# ---------------------------------------------------------------------------
# Step 2: the endpoint.
# ---------------------------------------------------------------------------
# `vllm serve` is run as a subprocess rather than using vLLM's Python `LLM`
# class, because it gives us the full OpenAI-compatible API for free. Modal
# proxies the port once vLLM is listening.
#
# requires_proxy_auth=True rejects unauthenticated requests at Modal's EDGE --
# before a container starts. Modal's official example ships an unauthenticated
# public URL; on a $30 budget that means anyone who finds the URL can start
# your A100. Modal prints a key icon next to the URL when this is on.


@app.function(
    image=image,
    gpu=GPU,
    volumes=VOLUMES,
    cpu=CPU_CORES,
    memory=MEMORY_MB,
    scaledown_window=IDLE_WINDOW_SECONDS,
    timeout=REQUEST_TIMEOUT_SECONDS,
)
@modal.concurrent(max_inputs=MAX_CONCURRENT_REQUESTS)
@modal.web_server(
    port=VLLM_PORT,
    startup_timeout=STARTUP_TIMEOUT_SECONDS,
    requires_proxy_auth=True,
)
def serve():
    cmd = [
        "vllm",
        "serve",
        MODEL_ID,
        "--host",
        "0.0.0.0",
        "--port",
        str(VLLM_PORT),
        "--max-model-len",
        str(MAX_MODEL_LEN),
        "--kv-cache-dtype",
        KV_CACHE_DTYPE,
        "--gpu-memory-utilization",
        str(GPU_MEMORY_UTILIZATION),
        # Separates the model's thinking from its answer in the API response.
        # From vLLM's published recipe for this model. Keep this even with
        # thinking disabled: it is what made the empty-answer failure visible
        # as empty `content` rather than as rambling answers.
        "--reasoning-parser",
        "qwen3",
        # Server-wide default for chat template kwargs. Set here rather than in
        # LiteLLM because chat_template_kwargs is a vLLM extension, not part of
        # the OpenAI spec -- routing it through a proxy means trusting that
        # proxy to forward a non-standard field. Setting it at the source also
        # covers callers that bypass the gateway.
        "--default-chat-template-kwargs",
        CHAT_TEMPLATE_KWARGS,
        # Lets clients send tool definitions and get structured tool_calls back.
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        TOOL_CALL_PARSER,
    ]
    print("starting:", " ".join(cmd))
    subprocess.Popen(cmd)
