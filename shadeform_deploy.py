#!/usr/bin/env python3
"""
Serve Qwen3.8-27B-FP8 on a rented Shadeform GPU VM with vLLM, using the
serving settings measured on Modal in phases 1-3.

    python3 shadeform_deploy.py offers                 # free: GPUs that can run it, cheapest first
    python3 shadeform_deploy.py up --hours 1           # PAID from here until the VM is deleted
    python3 shadeform_deploy.py up --hours 1 --https   # same, encrypted, firewall on
    python3 shadeform_deploy.py status                 # this tool's VMs, cost so far, time left
    python3 shadeform_deploy.py down                   # delete the VM; billing stops
    python3 shadeform_deploy.py reap                   # delete every VM past its deadline

Shadeform has no scale-to-zero: a VM bills from `up` until it is deleted.
Every VM therefore gets a deadline (`--hours`, required). Shadeform's own
auto-delete enforces it, and `reap` is the backup.

Standalone by design: Python 3 standard library only. Nothing here imports
deploy.py or needs the modal package, and deploy.py does not depend on this.

Secrets, read from .env next to this file (or from the environment):
    SHADEFORM_API_KEY   your Shadeform API key
    VLLM_API_KEY        the key the VM's vLLM requires; generated if missing

Why it is shaped this way: openspec/changes/shadeform-deployment/design.md
"""

import argparse
import base64
import datetime
import hashlib
import http.client
import json
import math
import os
import re
import secrets
import shlex
import signal
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Serving settings. They started equal to deploy.py's measured values (checked
# once, flag for flag, at delivery). From then on the two files are
# independent: tuning one never changes the other.
# ---------------------------------------------------------------------------

# The publisher's FP8 checkpoint, ~28 GB, downloaded by vLLM on every start.
MODEL_ID = "Qwen/Qwen3.8-27B-FP8"

# Just inside the 262,144 native limit, so no rope scaling. This caps one
# request's size; KV cache is allocated per actual token, not reserved.
MAX_MODEL_LEN = 250_000

# FP8 KV cache: twice BF16's room for concurrent long prompts. It passed the
# six long-document tasks again before being kept (phase 3).
KV_CACHE_DTYPE = "fp8"

GPU_MEMORY_UTILIZATION = 0.90

# Thinking goes to the `reasoning` field, the answer to `content`.
REASONING_PARSER = "qwen3"

# The shipped default ("xhigh") spent whole token budgets thinking and
# returned no answer. "low" answers within ordinary max_tokens; callers can
# ask for more per request with chat_template_kwargs.
CHAT_TEMPLATE_KWARGS = '{"reasoning_effort": "low"}'

# Structured tool calls for agents (Copilot, OpenCode), with auto tool choice.
TOOL_CALL_PARSER = "qwen3_xml"

# Multi-token prediction: ~2.8x faster decoding, kept under load (phase 3).
SPECULATIVE_CONFIG = '{"method": "mtp", "num_speculative_tokens": 3}'

# The official vLLM container, pinned to the version measured on Modal. It is
# built on CUDA 13.0, so the host driver must support CUDA 13 (see offers).
VLLM_IMAGE = "vllm/vllm-openai:v0.30.0"


def vllm_flags(tensor_parallel=1):
    """The vLLM flags after the model name, without host and port.

    For more than one GPU the split is appended at the end, so the shared part
    stays exactly as checked against deploy.py; for one GPU nothing changes."""
    flags = [
        "--max-model-len", str(MAX_MODEL_LEN),
        "--kv-cache-dtype", KV_CACHE_DTYPE,
        "--gpu-memory-utilization", str(GPU_MEMORY_UTILIZATION),
        "--reasoning-parser", REASONING_PARSER,
        "--default-chat-template-kwargs", CHAT_TEMPLATE_KWARGS,
        "--enable-auto-tool-choice",
        "--tool-call-parser", TOOL_CALL_PARSER,
        "--speculative-config", SPECULATIVE_CONFIG,
    ]
    if tensor_parallel > 1:
        flags += ["--tensor-parallel-size", str(tensor_parallel)]
    return flags


# ---------------------------------------------------------------------------
# VM settings
# ---------------------------------------------------------------------------

# 28.9 GiB of weights plus KV cache for 250K context; the A100-80GB is what
# phases 1-3 measured. Applies to every GPU, also when the model is split.
MIN_GPU_MEMORY_GB = 80

# --tensor-parallel: how many GPUs of one VM the model is split across. vLLM
# needs the split to divide the attention heads evenly; powers of two are the
# safe set. Only 1 (the default, unchanged) and 2 have been tested.
TENSOR_PARALLEL_CHOICES = (1, 2, 4, 8)

# The image's CUDA version. A host whose driver predates it cannot run the
# container, and a failed start costs money and 15+ minutes.
MIN_HOST_CUDA = (13, 0)

# The Shadeform account is a shared company workspace: this tool only ever
# deletes or reports instances whose names start with this prefix.
NAME_PREFIX = "qwen38-until-"

HTTP_PORT = 8000       # stage A: plain HTTP, for non-sensitive tests only
HTTPS_PORT = 8443      # stage B: TLS; the only port open besides SSH

MAX_CREATE_ATTEMPTS = 3   # offers can vanish between listing and creating
MAX_HOURS = 24            # a guard against typos in --hours
SPEND_MARGIN = 1.10       # auto-delete spend limit = hours x price x this

CONTAINER = "qwen38"
VM_DIR = "/opt/qwen38"    # on the VM: start log, model cache, key file, TLS files

API_URL = os.environ.get("SHADEFORM_API_URL", "https://api.shadeform.ai/v1")
POLL_SECONDS = float(os.environ.get("SHADEFORM_POLL_SECONDS", 15))
# Boot (up to 10 min) + 8.7 GB image + 28 GB model + vLLM start, with margin.
START_LIMIT_SECONDS = float(os.environ.get("SHADEFORM_START_LIMIT_SECONDS", 40 * 60))
DELETE_CONFIRM_SECONDS = float(os.environ.get("SHADEFORM_DELETE_CONFIRM_SECONDS", 5 * 60))
ENV_FILE = os.environ.get(
    "SHADEFORM_ENV_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def reach_port(port):
    """Where to connect for a VM port. Tests run a fake vLLM on a free local
    port and map it with SHADEFORM_TEST_PORT_<port>; normally unchanged."""
    return int(os.environ.get("SHADEFORM_TEST_PORT_%d" % port, port))


# ---------------------------------------------------------------------------
# Output and secrets. Everything printed goes through say(), which hides
# every secret the tool has loaded.
# ---------------------------------------------------------------------------

class Fail(Exception):
    """A clear, expected failure: printed as ERROR, exit status 1."""


_SECRETS = set()
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/=]{200,}")


def redact(text):
    for value in _SECRETS:
        text = text.replace(value, "<hidden>")
    return _BASE64_RUN.sub("<base64 hidden>", text)


def say(text=""):
    print(redact(str(text)), flush=True)


def short(body, limit=300):
    """An API response, shortened for an error message."""
    text = body if isinstance(body, str) else json.dumps(body)
    return text if len(text) <= limit else text[:limit] + "..."


def read_env_file():
    values = {}
    if not os.path.exists(ENV_FILE):
        return values
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            if name.startswith("export "):
                name = name[len("export "):].strip()
            values[name] = value.strip().strip('"').strip("'")
    return values


def secret(name):
    value = os.environ.get(name) or read_env_file().get(name)
    if value:
        _SECRETS.add(value)
    return value


def shadeform_key():
    key = secret("SHADEFORM_API_KEY")
    if not key:
        raise Fail("SHADEFORM_API_KEY is not set. Put SHADEFORM_API_KEY=<your key> "
                   "in %s (git-ignored)." % ENV_FILE)
    return key


def vllm_key():
    """The key vLLM will require. Generated and saved to .env if missing."""
    key = secret("VLLM_API_KEY")
    if key:
        if not re.fullmatch(r"[A-Za-z0-9._~+/=-]{16,}", key):
            raise Fail("VLLM_API_KEY in .env must be at least 16 characters, "
                       "with no spaces or quotes.")
        return key
    key = secrets.token_urlsafe(32)
    _SECRETS.add(key)
    new_file = not os.path.exists(ENV_FILE)
    needs_newline = False
    if not new_file:
        with open(ENV_FILE, "rb") as f:
            data = f.read()
        needs_newline = bool(data) and not data.endswith(b"\n")
    with open(ENV_FILE, "a") as f:
        f.write(("\n" if needs_newline else "") + "VLLM_API_KEY=%s\n" % key)
    if new_file:
        os.chmod(ENV_FILE, 0o600)
    say("Generated a new VLLM_API_KEY and saved it to %s (not shown)." % ENV_FILE)
    say("Give the gateway the same value as this model's API key.")
    return key


# ---------------------------------------------------------------------------
# Shadeform API
# ---------------------------------------------------------------------------

def api(method, path, key=None, body=None, timeout=60):
    """One Shadeform API call. Returns (HTTP status, parsed JSON or text).
    Network failures raise urllib.error.URLError or OSError."""
    headers = {"Accept": "application/json"}
    if key:
        headers["X-API-KEY"] = key
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(API_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    text = raw.decode("utf-8", "replace")
    try:
        return status, json.loads(text) if text else None
    except ValueError:
        return status, text


def check_auth(status):
    if status in (401, 403):
        raise Fail("Shadeform refused the API key (HTTP %d). Check SHADEFORM_API_KEY." % status)


def instance_info(key, iid):
    """The instance's /info, or None if Shadeform no longer knows it."""
    status, body = api("GET", "/instances/%s/info" % iid, key)
    check_auth(status)
    if status == 404:
        return None
    if status != 200 or not isinstance(body, dict):
        raise OSError("Shadeform /info answered HTTP %s: %s" % (status, short(body)))
    return body


def all_instances(key):
    """Every non-deleted instance on the account ('deleting' ones included)."""
    status, body = api("GET", "/instances", key)
    check_auth(status)
    if status != 200 or not isinstance(body, dict):
        raise OSError("Shadeform /instances answered HTTP %s: %s" % (status, short(body)))
    return body.get("instances") or []


def tool_instances(key):
    """This tool's instances (by name prefix). Others on the account are ignored."""
    return [i for i in all_instances(key) if str(i.get("name", "")).startswith(NAME_PREFIX)]


def _ignore_interrupts():
    """Ctrl-C, terminal close or kill must not stop a deletion halfway."""
    saved = {}
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            sig = getattr(signal, name)
            saved[sig] = signal.signal(sig, signal.SIG_IGN)
    return saved


def delete_and_confirm(key, iid):
    """Deletes the instance and waits until Shadeform reports `deleting`,
    `deleted` or no longer knows it. Shadeform stops billing at `deleting`."""
    saved = _ignore_interrupts()
    try:
        end = time.monotonic() + DELETE_CONFIRM_SECONDS
        next_request = 0.0
        while time.monotonic() < end:
            try:
                if time.monotonic() >= next_request:
                    status, body = api("POST", "/instances/%s/delete" % iid, key)
                    check_auth(status)
                    next_request = time.monotonic() + 30
                listed = [i for i in all_instances(key) if i.get("id") == iid]
                state = listed[0].get("status") if listed else "deleted"
                if state in ("deleting", "deleted"):
                    say("  %s: %s, confirmed by Shadeform; billing has stopped." % (iid, state))
                    return True
            except (urllib.error.URLError, OSError) as e:
                say("  %s: Shadeform not reachable (%s); retrying" % (iid, e))
            time.sleep(min(POLL_SECONDS, 5))
        say("  WARNING: %s: deletion NOT confirmed after %d s. It may still be billing." %
            (iid, DELETE_CONFIRM_SECONDS))
        say("  Run `python3 shadeform_deploy.py down %s` again, or check the dashboard." % iid)
        return False
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------

_CUDA = re.compile(r"cuda(\d+)\.(\d+)")


def host_cuda(os_name):
    m = _CUDA.search(os_name)
    return (int(m.group(1)), int(m.group(2))) if m else None


def split_offers(types, regions=None, clouds=None, gpus=None, tensor_parallel=1):
    """Turns /instances/types into (usable, not_usable) rows, cheapest first.

    Only offers with exactly `tensor_parallel` GPUs (1 unless asked), each 80 GB+,
    on-demand and available now, appear at all, one row per available region. A row is usable when one of its OS images ships
    a CUDA 13.0+ driver; otherwise it is listed as not usable, with the reason.
    `regions` match any part of the region name; `clouds` match exactly;
    `gpus` match any part of the GPU or instance type, e.g. H100 or A100."""
    usable, not_usable = [], []
    for t in types:
        conf = t.get("configuration") or {}
        if conf.get("num_gpus") != tensor_parallel or (conf.get("vram_per_gpu_in_gb") or 0) < MIN_GPU_MEMORY_GB:
            continue
        if clouds and t.get("cloud") not in clouds:
            continue
        kind = ("%s %s" % (conf.get("gpu_type"), t.get("shade_instance_type"))).lower()
        if gpus and not any(g.lower() in kind for g in gpus):
            continue
        images = sorted((host_cuda(o), "shade_os" in o, o)
                        for o in conf.get("os_options") or [] if host_cuda(o))
        best = images[-1] if images else None
        for a in t.get("availability") or []:
            if not a.get("available") or a.get("rental_type", "on_demand") != "on_demand":
                continue
            if regions and not any(r.lower() in a.get("region", "").lower() for r in regions):
                continue
            row = {
                "cloud": t.get("cloud"),
                "instance_type": t.get("shade_instance_type"),
                "region": a.get("region"),
                "where": a.get("display_name", ""),
                "gpu": conf.get("gpu_type"),
                "vram_gb": conf.get("vram_per_gpu_in_gb"),
                "price_cents": t.get("hourly_price"),
                "os": best[2] if best else None,
                "num_gpus": conf.get("num_gpus"),
                "link": link_text(conf),
            }
            if best and best[0] >= MIN_HOST_CUDA:
                usable.append(row)
            else:
                row["reason"] = ("newest host CUDA is %d.%d" % best[0]) if best \
                    else "no CUDA image offered"
                not_usable.append(row)

    def order(r):
        return (r["price_cents"] if r["price_cents"] is not None else 10**9, r["cloud"], r["region"])
    return sorted(usable, key=order), sorted(not_usable, key=order)


def link_text(conf):
    """How the GPUs of an offer are connected, as Shadeform describes it."""
    if conf.get("nvlink"):
        return "NVLink"
    link = {"pcie": "PCIe"}.get(conf.get("interconnect"), conf.get("interconnect") or "unknown link")
    return "%s, no NVLink" % link


def gpu_summary(offer, tensor_parallel):
    """e.g. '2 x A100_80G (80 GB each), tensor parallel 2, link: PCIe, no NVLink (per Shadeform)'."""
    return "%d x %s (%d GB each), tensor parallel %d, link: %s (per Shadeform)" % (
        offer["num_gpus"], offer["gpu"], offer["vram_gb"], tensor_parallel, offer["link"])


def fetch_types(key=None):
    status, body = api("GET", "/instances/types", key)
    check_auth(status)
    if status != 200 or not isinstance(body, dict):
        raise Fail("Shadeform /instances/types answered HTTP %s: %s" % (status, short(body)))
    return body.get("instance_types") or []


def _offer_line(r, last, link=False):
    line = "  %6.2f  %-18s %-15s %-18s %s" % (
        r["price_cents"] / 100.0, r["instance_type"], r["cloud"], r["region"], last)
    if link:            # multi-GPU listings only; the one-GPU listing keeps its columns
        line = "  %6.2f  %-18s %-15s %-18s %-17s %s" % (
            r["price_cents"] / 100.0, r["instance_type"], r["cloud"], r["region"], r["link"], last)
    return line


def _filters(args):
    def values(items):
        out = [v.strip() for item in items or [] for v in item.split(",") if v.strip()]
        return out or None
    return values(args.region), values(args.cloud), values(args.gpu)


def cmd_offers(args):
    regions, clouds, gpus = _filters(args)
    tp = args.tensor_parallel
    usable, not_usable = split_offers(fetch_types(secret("SHADEFORM_API_KEY")), regions, clouds, gpus, tp)
    cuda = "%d.%d" % MIN_HOST_CUDA
    multi = tp > 1
    if multi:
        say("Usable now (%d GPUs on one VM, %d GB+ each, host CUDA %s+; price for the whole VM), "
            "cheapest first:" % (tp, MIN_GPU_MEMORY_GB, cuda))
        say("    $/hr  %-18s %-15s %-18s %-17s %s" % ("type", "provider", "region", "link", "OS image"))
    else:
        say("Usable now (1 GPU, %d GB+, host CUDA %s+), cheapest first:" % (MIN_GPU_MEMORY_GB, cuda))
        say("    $/hr  %-18s %-15s %-18s %s" % ("type", "provider", "region", "OS image"))
    for r in usable:
        say(_offer_line(r, r["os"], multi))
    if not usable:
        say("  (none right now; `up` would create nothing)")
    if not_usable:
        say()
        say("Not usable (the %s image needs a CUDA %s+ host driver):" % (VLLM_IMAGE, cuda))
        for r in not_usable:
            say(_offer_line(r, r["reason"], multi))
    return 0


# ---------------------------------------------------------------------------
# The VM's startup script
# ---------------------------------------------------------------------------

def startup_script(api_key, https=False, tensor_parallel=1):
    """The bash script Shadeform runs once the VM is active. It starts the
    pinned vLLM container with the settings above; with https it also makes a
    self-signed certificate and closes every port except SSH and 8443. With
    tensor_parallel > 1 it checks the GPU count, logs how the GPUs are linked,
    and splits the model; with 1 the script is exactly the single-GPU one.

    Every vLLM argument is quoted here, so JSON values reach vLLM intact."""
    port = HTTPS_PORT if https else HTTP_PORT
    multi = tensor_parallel > 1
    serve = [MODEL_ID, "--host", "0.0.0.0", "--port", str(port)] + vllm_flags(tensor_parallel)
    if https:
        serve += ["--ssl-keyfile", "/tls/key.pem", "--ssl-certfile", "/tls/cert.pem"]
    q = shlex.quote
    lines = [
        "#!/bin/bash",
        "# Written by shadeform_deploy.py. Starts vLLM serving %s" % MODEL_ID,
        "# (%s, port %d). Shadeform runs it once the VM is active." % (
            "HTTPS" if https else "plain HTTP", port),
        "set -euo pipefail",
        'DIR="${QWEN38_DIR:-%s}"' % VM_DIR,
        'SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo -n"',
        '$SUDO mkdir -p "$DIR"; $SUDO chown "$(id -u)" "$DIR"',
        'LOG="$DIR/start.log"',
        'exec > >(tee -a "$LOG") 2>&1',
        'step() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }',
        "trap 'step \"FATAL: line $LINENO failed with status $?\"' ERR",
        "step %s" % q("start: mode=%s port=%d image=%s%s" % (
            "https" if https else "http", port, VLLM_IMAGE,
            " tensor_parallel=%d" % tensor_parallel if multi else "")),
        "",
        "# The image is CUDA 13.0: the host driver must be 580 or newer.",
        "nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader",
        'DRIVER="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1)"',
        'if [ "${DRIVER%%.*}" -lt 580 ]; then',
        '  step "FATAL: driver $DRIVER is too old for the CUDA 13 image (needs 580+)"; exit 1',
        "fi",
        'df -h / "$DIR" || true',
    ]
    if multi:
        lines += [
            "",
            "# Tensor parallel: the model is split across %d GPUs, so all of them must" % tensor_parallel,
            "# be here. The topology shows how they are linked (PCIe, NVLink).",
            'GPUS="$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)"',
            'if [ "$GPUS" -lt %d ]; then' % tensor_parallel,
            '  step "FATAL: %d GPUs requested, $GPUS found"; exit 1' % tensor_parallel,
            "fi",
            'step "GPUs: $GPUS, tensor parallel %d; topology:"' % tensor_parallel,
            "nvidia-smi topo -m || true",
        ]
    lines += [
        "",
        "# The key vLLM requires, readable only by this user; docker reads it with --env-file.",
        'umask 077',
        "printf '%%s\\n' %s > \"$DIR/vllm.env\"" % q("VLLM_API_KEY=" + api_key),
        'umask 022',
        'mkdir -p "$DIR/hf-cache"',
    ]
    if https:
        lines += [
            "",
            'step "TLS: self-signed certificate"',
            'mkdir -p "$DIR/tls"',
            'openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=qwen38" \\',
            '  -keyout "$DIR/tls/key.pem" -out "$DIR/tls/cert.pem"',
            'chmod 600 "$DIR/tls/key.pem"',
            'openssl x509 -in "$DIR/tls/cert.pem" -noout -fingerprint -sha256',
            "",
            "# Docker-published ports bypass UFW, so only 8443 is published; UFW",
            "# closes everything else. SSH stays open on 22 and wherever sshd listens.",
            "# Reset first: provider images can ship their own rules (MassedCompute's",
            "# allowed port 80, seen 2026-10-01).",
            'step "firewall: deny incoming except SSH and %d"' % HTTPS_PORT,
            "command -v ufw >/dev/null || { $SUDO apt-get update -qq && $SUDO apt-get install -y -qq ufw; }",
            "$SUDO ufw --force reset",
            "$SUDO ufw default deny incoming",
            "$SUDO ufw default allow outgoing",
            "$SUDO ufw allow 22/tcp",
            "for p in $($SUDO ss -Htlnp 2>/dev/null | awk '/sshd/ {n=split($4,a,\":\"); print a[n]}' | sort -u); do",
            '  $SUDO ufw allow "$p/tcp"',
            "done",
            "$SUDO ufw allow %d/tcp" % HTTPS_PORT,
            "$SUDO ufw --force enable",
            "$SUDO ufw status verbose",
        ]
    mounts = ['-v "$DIR/hf-cache:/root/.cache/huggingface"']
    if https:
        mounts.append('-v "$DIR/tls:/tls:ro"')
    lines += [
        "",
        "$SUDO docker version --format 'docker client {{.Client.Version}}, server {{.Server.Version}}'",
        "step %s" % q("pulling %s (8.7 GB)" % VLLM_IMAGE),
        "$SUDO docker pull %s" % q(VLLM_IMAGE),
        "$SUDO docker rm -f %s >/dev/null 2>&1 || true" % CONTAINER,
        "SERVE_ARGS=(%s)" % " ".join(q(a) for a in serve),
        'step "starting vLLM; the model (~28 GB) downloads on first start"',
        # Tensor parallel workers exchange data through shared memory: vLLM's docs
        # give --ipc=host for that. One GPU keeps the measured 16 GB.
        "$SUDO docker run -d --name %s --restart on-failure:3 --gpus all %s \\" % (
            CONTAINER, "--ipc=host" if multi else "--shm-size 16g"),
        "  -p %d:%d %s \\" % (port, port, " ".join(mounts)),
        '  --env-file "$DIR/vllm.env" -e HF_HUB_DISABLE_XET=1 \\',
        '  %s "${SERVE_ARGS[@]}"' % q(VLLM_IMAGE),
        'step "container started; follow it with: sudo docker logs -f %s"' % CONTAINER,
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Up
# ---------------------------------------------------------------------------

def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def deadline_after(hours):
    """Now + hours, rounded up to the minute (the instance name has minutes)."""
    t = utcnow() + datetime.timedelta(hours=hours)
    if t.second or t.microsecond:
        t = t.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
    return t


def instance_name(deadline):
    return NAME_PREFIX + deadline.strftime("%Y%m%dT%H%MZ")


def name_deadline(name):
    """The deadline recorded in a tool instance's name, or None if unreadable."""
    m = re.fullmatch(re.escape(NAME_PREFIX) + r"(\d{8}T\d{4})Z", str(name))
    if not m:
        return None
    return datetime.datetime.strptime(m.group(1), "%Y%m%dT%H%M").replace(
        tzinfo=datetime.timezone.utc)


def spend_limit(hours, price_cents):
    """Dollars for Shadeform's auto-delete spend threshold: a second trigger,
    a little above what the deadline alone allows."""
    # round() first: 330 x 1.1 is 363.00000000000006 in floating point, not 363
    return math.ceil(round(hours * price_cents * SPEND_MARGIN, 6)) / 100.0


def create_request(offer, name, deadline, hours, script, ssh_key_id=None):
    body = {
        "cloud": offer["cloud"],
        "region": offer["region"],
        "shade_instance_type": offer["instance_type"],
        "shade_cloud": True,
        "name": name,
        "os": offer["os"],
        "auto_delete": {
            "date_threshold": deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "spend_threshold": "%.2f" % spend_limit(hours, offer["price_cents"]),
        },
        "launch_configuration": {
            "type": "script",
            "script_configuration": {
                "base64_script": base64.b64encode(script.encode()).decode(),
            },
        },
    }
    if ssh_key_id:
        body["ssh_key_id"] = ssh_key_id
    return body


def _elapsed(t0):
    s = int(time.monotonic() - t0)
    return "%dm%02ds" % (s // 60, s % 60)


def _duration(seconds):
    seconds = int(abs(seconds))
    h, m = seconds // 3600, seconds % 3600 // 60
    return "%dh%02dm" % (h, m) if h else "%dm" % m


def vm_request(ip, port, method, path, key=None, body=None, https=False, timeout=30):
    """One HTTP(S) request to the VM. Returns (status, body, certificate DER).
    Status is None when nothing answers on that port (yet)."""
    if https:
        # Self-signed: identity is checked by fingerprint, not by a CA.
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(ip, reach_port(port), timeout=timeout, context=context)
    else:
        conn = http.client.HTTPConnection(ip, reach_port(port), timeout=timeout)
    headers = {}
    if key:
        headers["Authorization"] = "Bearer " + key
    data = None
    if body is not None:
        data = json.dumps(body)
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, path, body=data, headers=headers)
        cert = conn.sock.getpeercert(binary_form=True) if https else None
        response = conn.getresponse()
        raw = response.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = raw
        return response.status, parsed, cert
    except (OSError, http.client.HTTPException) as e:
        return None, str(e) or e.__class__.__name__, None
    finally:
        conn.close()


def port_open(ip, port, timeout=5):
    try:
        socket.create_connection((ip, reach_port(port)), timeout=timeout).close()
        return True
    except OSError:
        return False


def fingerprint(der):
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


class Start:
    """What `up` knows so far, for progress lines and the failure report."""

    def __init__(self, iid, offer, https, tensor_parallel=1):
        self.iid, self.offer, self.https = iid, offer, https
        self.tensor_parallel = tensor_parallel
        self.gpus_checked = tensor_parallel == 1    # one GPU: no extra check, as before
        self.t0 = time.monotonic()
        self.stage = "creating the VM"
        self.ip = None
        self.ssh_user = "shadeform"
        self.cert = None
        self.last_print = 0.0

    def progress(self, stage, detail=""):
        changed = stage != self.stage
        self.stage = stage
        if changed or time.monotonic() - self.last_print >= 120:
            say("  %7s  %s%s" % (_elapsed(self.t0), stage, " (%s)" % detail if detail else ""))
            self.last_print = time.monotonic()

    def check_time(self):
        if time.monotonic() - self.t0 > START_LIMIT_SECONDS:
            raise Fail("not ready after %d minutes" % (START_LIMIT_SECONDS // 60))

    def check_cert(self, cert):
        """The certificate must not change during the start."""
        if not cert:
            return
        if self.cert is None:
            self.cert = cert
        elif cert != self.cert:
            raise Fail("SECURITY: the VM's certificate changed during the start")

    def vm_state(self, key):
        """Polls /info; fails on error or an unexpected deletion."""
        try:
            info = instance_info(key, self.iid)
        except (urllib.error.URLError, OSError) as e:
            self.progress(self.stage, "Shadeform not reachable: %s" % e)
            return None
        if info is None:
            raise Fail("Shadeform no longer knows the VM (deleted elsewhere?)")
        status = info.get("status")
        if status == "error":
            raise Fail("Shadeform reports status 'error': %s" % (info.get("status_details") or "no details"))
        if status in ("deleting", "deleted"):
            raise Fail("the VM is being deleted (by auto-delete, or from elsewhere)")
        self.ssh_user = info.get("ssh_user") or self.ssh_user
        return info


def wait_until_ready(key, start, api_key):
    """VM active -> vLLM answers with the key -> refuses without it -> (https
    checks) -> a real chat completion. Raises Fail on error or time limit."""
    port = HTTPS_PORT if start.https else HTTP_PORT

    while True:
        start.check_time()
        info = start.vm_state(key)
        if info and not start.gpus_checked:
            # The first /info after create already describes the machine: a VM with
            # the wrong GPU count is deleted now, not after the 40-minute limit.
            found = (info.get("configuration") or {}).get("num_gpus")
            if found is not None and found != start.tensor_parallel:
                raise Fail("Shadeform's VM has %s GPU(s), %d were requested"
                           % (found, start.tensor_parallel))
            start.gpus_checked = True
        if info:
            status = info.get("status") or "unknown"
            if status == "active" and info.get("ip"):
                start.ip = info["ip"]
                break
            start.progress("VM %s" % status, info.get("status_details") or "")
        time.sleep(POLL_SECONDS)

    say("  %7s  VM active at %s. Watch the start over SSH if you like:" % (_elapsed(start.t0), start.ip))
    say("             ssh %s@%s 'tail -f %s/start.log'" % (start.ssh_user, start.ip, VM_DIR))
    while True:
        start.check_time()
        start.vm_state(key)
        status, body, cert = vm_request(start.ip, port, "GET", "/v1/models", api_key, https=start.https)
        start.check_cert(cert)
        if status == 200:
            break
        if status in (401, 403):
            raise Fail("vLLM on the VM refused our key (HTTP %d)" % status)
        start.progress("waiting for vLLM on port %d: image pull, ~28 GB model download, load" % port,
                       "HTTP %s" % status if status else "not answering yet")
        time.sleep(POLL_SECONDS)

    status, _, cert = vm_request(start.ip, port, "GET", "/v1/models", None, https=start.https)
    start.check_cert(cert)
    if status != 401:
        raise Fail("SECURITY: the endpoint did not refuse a request without the key (HTTP %s)" % status)
    start.progress("vLLM answering; a request without the key is refused (401)")

    if start.https:
        # No key on this probe: it is the unencrypted path being tested.
        status, _, _ = vm_request(start.ip, HTTPS_PORT, "GET", "/v1/models", None, https=False)
        if status in (200, 401, 403):
            raise Fail("SECURITY: port %d also answers plain HTTP (HTTP %s)" % (HTTPS_PORT, status))
        if port_open(start.ip, HTTP_PORT):
            raise Fail("SECURITY: port %d accepts connections; the firewall is not closing it" % HTTP_PORT)
        start.progress("HTTPS only: plain HTTP is refused and port %d is closed" % HTTP_PORT)

    request = {"model": MODEL_ID, "max_tokens": 400,
               "messages": [{"role": "user", "content": "Reply with one word: ready"}]}
    while True:
        start.check_time()
        status, body, cert = vm_request(start.ip, port, "POST", "/v1/chat/completions", api_key,
                                        request, https=start.https, timeout=300)
        start.check_cert(cert)
        try:
            answer = (body["choices"][0]["message"].get("content") or "").strip()
        except (TypeError, KeyError, IndexError, AttributeError):
            answer = ""
        if status == 200 and answer:
            return answer
        start.progress("waiting for a real answer to a test question",
                       "HTTP %s, %s" % (status, "empty answer" if status == 200 else short(body, 120)))
        time.sleep(POLL_SECONDS)


def create_vm(key, offers, name, deadline, hours, script, ssh_key_id):
    """Creates the VM on the first offer that accepts it, up to 3 offers."""
    for offer in offers[:MAX_CREATE_ATTEMPTS]:
        body = create_request(offer, name, deadline, hours, script, ssh_key_id)
        try:
            status, response = api("POST", "/instances/create", key, body)
        except (urllib.error.URLError, OSError) as e:
            raise Fail("lost contact with Shadeform during create (%s). A VM may exist: "
                       "run `status`, then `down`." % e)
        check_auth(status)
        if status in (200, 201) and isinstance(response, dict) and response.get("id"):
            return response["id"], offer
        say("  %s %s refused the create (HTTP %s: %s)" % (
            offer["cloud"], offer["region"], status, short(response, 200)))
        if offer is not offers[min(len(offers), MAX_CREATE_ATTEMPTS) - 1]:
            say("  trying the next offer")
    raise Fail("no offer accepted the create request (tried %d). Nothing was created."
               % min(len(offers), MAX_CREATE_ATTEMPTS))


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def cmd_up(args):
    hours = args.hours
    if not 0 < hours <= MAX_HOURS:
        raise Fail("--hours must be more than 0 and at most %d." % MAX_HOURS)
    key = shadeform_key()
    regions, clouds, gpus = _filters(args)
    tp = args.tensor_parallel
    usable, not_usable = split_offers(fetch_types(key), regions, clouds, gpus, tp)
    if not usable:
        raise Fail("no usable offer right now%s (run `offers` to see why). Nothing was created."
                   % (" for those filters" if regions or clouds or gpus or tp > 1 else ""))
    api_key = vllm_key()

    deadline = deadline_after(hours)
    name = instance_name(deadline)
    offer = usable[0]
    say("Plan:")
    if tp > 1:
        say("  offer     %s %s %s (%s), $%.2f/hr for the whole VM" % (
            offer["cloud"], offer["instance_type"], offer["region"], offer["where"],
            offer["price_cents"] / 100.0))
        say("  GPUs      %s" % gpu_summary(offer, tp))
    else:
        say("  offer     %s %s %s (%s), %d GB GPU, $%.2f/hr" % (
            offer["cloud"], offer["instance_type"], offer["region"], offer["where"], offer["vram_gb"],
            offer["price_cents"] / 100.0))
    if len(usable) > 1:
        say("            if it has no capacity: up to %d more offers, cheapest first"
            % (min(len(usable), MAX_CREATE_ATTEMPTS) - 1))
    say("  deadline  %s (Shadeform auto-deletes it then; `reap` is the backup)"
        % deadline.strftime("%Y-%m-%d %H:%M UTC"))
    say("  cost cap  about $%.2f (Shadeform's auto-delete spend limit)"
        % spend_limit(hours, offer["price_cents"]))
    if args.https:
        say("  mode      HTTPS on port %d, self-signed certificate, firewall: SSH and %d only"
            % (HTTPS_PORT, HTTPS_PORT))
    else:
        say("  mode      PLAIN HTTP on port %d" % HTTP_PORT)
        say()
        say("  WARNING: plain HTTP is NOT encrypted. The key and every prompt and answer")
        say("  cross the internet readable by anyone on the path. Non-sensitive tests only;")
        say("  use --https before any company data.")
    say()
    say("Billing starts when the VM is created and stops when it is deleted.")
    if not args.yes:
        if not sys.stdin.isatty():
            raise Fail("this creates a paid VM. Run it in a terminal to confirm, or add --yes.")
        if input("Create it now? [y/N] ").strip().lower() not in ("y", "yes"):
            say("Cancelled. Nothing was created.")
            return 1

    script = startup_script(api_key, https=args.https, tensor_parallel=tp)
    for sig_name in ("SIGTERM", "SIGHUP"):     # treated like Ctrl-C: delete, then exit
        if hasattr(signal, sig_name):
            signal.signal(getattr(signal, sig_name), _raise_interrupt)
    saved = _ignore_interrupts()      # a create cut short could leave a VM we cannot see
    try:
        iid, offer = create_vm(key, usable, name, deadline, hours, script, args.ssh_key_id)
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)
    start = Start(iid, offer, args.https, tp)
    say("Created %s (%s) on %s %s, $%.2f/hr." % (
        iid, name, offer["cloud"], offer["region"], offer["price_cents"] / 100.0))
    try:
        answer = wait_until_ready(key, start, api_key)
    except BaseException as e:
        interrupted = isinstance(e, KeyboardInterrupt)
        say()
        say("FAILED: %s." % ("interrupted" if interrupted else e))
        say("  last stage: %s, after %s" % (start.stage, _elapsed(start.t0)))
        say("Deleting the VM so it stops billing...")
        delete_and_confirm(key, iid)
        if not interrupted and start.ip:
            say("Next time, watch the start live over SSH to see why: "
                "ssh %s@%s 'tail -f %s/start.log', then 'sudo docker logs %s'."
                % (start.ssh_user, start.ip, VM_DIR, CONTAINER))
        return 130 if interrupted else 1

    scheme, port = ("https", HTTPS_PORT) if args.https else ("http", HTTP_PORT)
    say()
    say("READY after %s: the model answered %r." % (_elapsed(start.t0), answer[:40]))
    say()
    say("  VM        %s  %s %s, %s, $%.2f/hr" % (
        iid, offer["cloud"], offer["region"], offer["instance_type"], offer["price_cents"] / 100.0))
    say("  deadline  %s, then Shadeform deletes it" % deadline.strftime("%Y-%m-%d %H:%M UTC"))
    if tp > 1:
        say("  GPUs      %s" % gpu_summary(offer, tp))
        say("            all %d in use (vLLM refuses to start the split on fewer); topology in %s/start.log"
            % (tp, VM_DIR))
    if not args.https:
        say("  mode      PLAIN HTTP, not encrypted: non-sensitive tests only")
    say()
    say("Gateway (LiteLLM) settings for this model:")
    say("  API Base            %s://%s:%d/v1" % (scheme, start.ip, port))
    say("  API Key             the VLLM_API_KEY value in .env (not printed here)")
    say("  Provider / Model    vLLM (hosted_vllm) / %s" % MODEL_ID)
    say("  Timeout             900 s")
    if args.https:
        say("  ssl_verify          false (the certificate is self-signed). Use the vLLM provider:")
        say("                      LiteLLM's openai provider ignores a per-model ssl_verify")
        say("  certificate SHA-256 %s" % fingerprint(start.cert))
        say("                      (compare over SSH: 'openssl x509 -in %s/tls/cert.pem -noout "
            "-fingerprint -sha256')" % VM_DIR)
    say()
    say("Close it when you are done; billing stops at once:")
    say("  python3 shadeform_deploy.py down %s" % iid)
    return 0


# ---------------------------------------------------------------------------
# Status, down, reap
# ---------------------------------------------------------------------------

def _time_left(name, now):
    deadline = name_deadline(name)
    if deadline is None:
        return "deadline unreadable"
    left = (deadline - now).total_seconds()
    return _duration(left) if left > 0 else "OVERDUE by %s (run reap)" % _duration(left)


def _parse_time(text):
    try:
        return datetime.datetime.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def cmd_status(args):
    key = shadeform_key()
    mine = tool_instances(key)
    if not mine:
        say("No instances from this tool (names %s*). Nothing is billing from it." % NAME_PREFIX)
        return 0
    now = utcnow()
    say("Instances from this tool (other instances on the account are not shown):")
    for i in mine:
        created = _parse_time(i.get("created_at"))
        up_for = _duration((now - created).total_seconds()) if created else "?"
        price = i.get("hourly_price")
        say("  %s  %s" % (i.get("id"), i.get("name")))
        say("      %s %s, ip %s, status %s" % (
            i.get("cloud"), i.get("region"), i.get("ip") or "-", i.get("status")))
        say("      $%s/hr, cost so far $%s (Shadeform's estimate), up for %s, time left %s" % (
            "%.2f" % (price / 100.0) if isinstance(price, (int, float)) else "?",
            i.get("cost_estimate", "?"), up_for, _time_left(i.get("name"), now)))
    return 0


def cmd_down(args):
    key = shadeform_key()
    if args.id:
        info = instance_info(key, args.id)
        if info is None:
            raise Fail("Shadeform has no instance %s (already deleted?)." % args.id)
        if not str(info.get("name", "")).startswith(NAME_PREFIX):
            raise Fail("refusing: %s is named %r, so this tool did not create it."
                       % (args.id, info.get("name")))
        targets = [info]
    else:
        targets = [i for i in tool_instances(key) if i.get("status") not in ("deleting", "deleted")]
        if not targets:
            say("No running instances from this tool. Nothing to delete.")
            return 0
        if len(targets) > 1:
            say("Several instances from this tool are running:")
            for i in targets:
                say("  %s  %s  %s" % (i.get("id"), i.get("name"), i.get("status")))
            raise Fail("say which one: python3 shadeform_deploy.py down <id>")
    ok = True
    for i in targets:
        say("Deleting %s (%s)..." % (i.get("id"), i.get("name")))
        ok = delete_and_confirm(key, i["id"]) and ok
    return 0 if ok else 1


def cmd_reap(args):
    key = shadeform_key()
    now = utcnow()
    live = [i for i in tool_instances(key) if i.get("status") not in ("deleting", "deleted")]
    expired = [i for i in live if name_deadline(i.get("name")) and name_deadline(i.get("name")) <= now]
    for i in live:
        if name_deadline(i.get("name")) is None:
            say("WARNING: %s has an unreadable deadline (%s); not touched." % (i.get("id"), i.get("name")))
    ok = True
    for i in expired:
        say("%s is past its deadline (%s ago): deleting" % (
            i.get("id"), _duration((now - name_deadline(i.get("name"))).total_seconds())))
        ok = delete_and_confirm(key, i["id"]) and ok
    say("reap %s: %d deleted, %d still within their deadline." % (
        now.strftime("%Y-%m-%d %H:%M UTC"), len(expired), len(live) - len(expired)))
    return 0 if ok else 1


# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="shadeform_deploy.py",
        description="Serve %s on a rented Shadeform GPU VM. Standard library only." % MODEL_ID)
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    def filters(p):
        p.add_argument("--region", action="append", metavar="NAME",
                       help="only regions containing NAME, e.g. france or desmoines-usa-1 "
                            "(repeat or comma-separate)")
        p.add_argument("--gpu", action="append", metavar="NAME",
                       help="only these GPUs, e.g. H100 or A100 (matches any part of the GPU "
                            "or instance type; repeat or comma-separate)")
        p.add_argument("--cloud", action="append", metavar="NAME",
                       help="only these providers, e.g. massedcompute (repeat or comma-separate)")
        p.add_argument("--tensor-parallel", type=int, default=1, choices=TENSOR_PARALLEL_CHOICES,
                       metavar="N",
                       help="split the model across N GPUs of one VM (1, 2, 4 or 8; default 1, "
                            "which is the normal single-GPU setup)")

    p = sub.add_parser("offers", help="free: list GPUs that can run the model, cheapest first")
    filters(p)
    p.set_defaults(func=cmd_offers)

    p = sub.add_parser("up", help="PAID: create a VM and wait until the model answers")
    p.add_argument("--hours", type=float, required=True,
                   help="required: the VM is deleted after this many hours (fractions allowed, max %d)"
                        % MAX_HOURS)
    p.add_argument("--https", action="store_true",
                   help="serve HTTPS on %d with a firewall (required before company data)" % HTTPS_PORT)
    p.add_argument("--yes", action="store_true", help="do not ask before creating the paid VM")
    p.add_argument("--ssh-key-id", metavar="ID",
                   help="Shadeform SSH key to install (default: the account's default key)")
    filters(p)
    p.set_defaults(func=cmd_up)

    p = sub.add_parser("status", help="free: this tool's VMs, cost so far and time left")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("down", help="delete the VM and confirm billing stopped")
    p.add_argument("id", nargs="?", help="instance id (needed only if several are running)")
    p.set_defaults(func=cmd_down)

    p = sub.add_parser("reap", help="delete every VM from this tool past its deadline (for cron)")
    p.set_defaults(func=cmd_reap)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except Fail as e:
        say("ERROR: %s" % e)
        return 1
    except (urllib.error.URLError, OSError) as e:
        say("ERROR: cannot reach Shadeform (%s)." % getattr(e, "reason", e))
        return 1
    except KeyboardInterrupt:
        say("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
