"""Checks the create request and the VM's startup script that
shadeform_deploy.py sends, by running the script here with fake docker,
nvidia-smi, ufw and openssl. It proves the exact arguments vLLM would
receive, with no VM and no cost.

    python3 tests/test_shadeform_script.py
"""

import base64
import datetime
import json
import os
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import shadeform_deploy as sd  # noqa: E402

KEY = "vllm-dummy-key-4b2d8f6e1a9c"
OFFER = {"cloud": "massedcompute", "region": "desmoines-usa-1", "instance_type": "A100_sxm4_80G",
         "price_cents": 138, "os": "ubuntu22.04_cuda13.0_shade_os"}
DEADLINE = datetime.datetime(2026, 10, 1, 19, 0, tzinfo=datetime.timezone.utc)

# Every fake records its name and arguments, one JSON line per call.
FAKE = r'''#!/usr/bin/env python3
import json, os, sys
name, args = os.path.basename(sys.argv[0]), sys.argv[1:]
if name == "sudo":
    if args[:1] == ["-n"]:
        args = args[1:]
    os.execvp(args[0], args)
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps({"cmd": name, "args": args}) + "\n")
driver = os.environ.get("FAKE_DRIVER", "580.82.07")
gpus = int(os.environ.get("FAKE_GPUS", "1"))
if name == "nvidia-smi" and args[:1] == ["topo"]:
    print("        GPU0    GPU1\nGPU0     X      PHB\nGPU1    PHB      X")
elif name == "nvidia-smi":
    for i in range(gpus):
        if "--query-gpu=index" in args:
            print(i)
        elif "--query-gpu=driver_version" in args:
            print(driver)
        else:
            print("NVIDIA A100-SXM4-80GB, %s, 81920 MiB" % driver)
elif name == "docker" and args[:1] == ["version"]:
    print("docker client 27.3.1, server 27.3.1")
elif name == "openssl" and args[:1] == ["req"]:
    for flag in ("-keyout", "-out"):
        open(args[args.index(flag) + 1], "w").write("fake pem\n")
elif name == "openssl" and args[:1] == ["x509"]:
    print("sha256 Fingerprint=AA:BB:CC")
elif name == "ss":
    print('LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=812,fd=3))')
    print('LISTEN 0 128 0.0.0.0:2222 0.0.0.0:* users:(("sshd",pid=812,fd=4))')
'''


def run_script(script, driver="580.82.07", gpus=1):
    """Runs the startup script with the fakes first on PATH, as a normal
    user (so its sudo path runs too). Returns (process, VM dir, calls)."""
    tmp = tempfile.mkdtemp()
    bin_dir, vm_dir = os.path.join(tmp, "bin"), os.path.join(tmp, "vm")
    os.makedirs(bin_dir)
    for name in ("docker", "nvidia-smi", "ufw", "openssl", "ss", "apt-get", "sudo"):
        path = os.path.join(bin_dir, name)
        with open(path, "w") as f:
            f.write(FAKE)
        os.chmod(path, 0o755)
    path = os.path.join(tmp, "startup.sh")
    with open(path, "w") as f:
        f.write(script)
    calls = os.path.join(tmp, "calls.jsonl")
    env = {"PATH": bin_dir + ":/usr/bin:/bin", "HOME": tmp, "QWEN38_DIR": vm_dir,
           "FAKE_CALLS": calls, "FAKE_DRIVER": driver, "FAKE_GPUS": str(gpus)}
    proc = subprocess.run(["bash", path], env=env, capture_output=True, text=True, timeout=60)
    recorded = [json.loads(line) for line in open(calls)] if os.path.exists(calls) else []
    return proc, vm_dir, recorded


def docker_run(calls):
    runs = [c["args"] for c in calls if c["cmd"] == "docker" and c["args"][:1] == ["run"]]
    assert len(runs) == 1, runs
    return runs[0]


# 1. The create request: name, os, auto-delete, and a script launch only.
script_a = sd.startup_script(KEY, https=False)
body = sd.create_request(OFFER, sd.instance_name(DEADLINE), DEADLINE, 1.5, script_a)
assert body["name"] == "qwen38-until-20261001T1900Z", body["name"]
assert sd.name_deadline(body["name"]) == DEADLINE
assert (body["cloud"], body["region"], body["shade_instance_type"], body["shade_cloud"]) == \
    ("massedcompute", "desmoines-usa-1", "A100_sxm4_80G", True), body
assert body["os"] == "ubuntu22.04_cuda13.0_shade_os", body["os"]
# 1.5 h x $1.38 x 1.10 = $2.277, rounded up to the cent
assert body["auto_delete"] == {"date_threshold": "2026-10-01T19:00:00Z", "spend_threshold": "2.28"}, \
    body["auto_delete"]
launch = body["launch_configuration"]
assert launch["type"] == "script" and set(launch) == {"type", "script_configuration"}, launch
decoded = base64.b64decode(launch["script_configuration"]["base64_script"]).decode()
assert decoded == script_a
assert KEY not in json.dumps(body), "the key travels only inside the base64 script"
assert "ssh_key_id" not in body
assert sd.create_request(OFFER, "n", DEADLINE, 1, script_a, "key-123")["ssh_key_id"] == "key-123"

# 2. Both scripts are valid bash.
script_b = sd.startup_script(KEY, https=True)
for s in (script_a, script_b):
    check = subprocess.run(["bash", "-n"], input=s, capture_output=True, text=True)
    assert check.returncode == 0, check.stderr

# 3. Stage A, run with fakes: the exact docker run, JSON values intact.
proc, vm, calls = run_script(script_a)
assert proc.returncode == 0, proc.stdout + proc.stderr
expected = [
    "run", "-d", "--name", "qwen38", "--restart", "on-failure:3", "--gpus", "all",
    "--shm-size", "16g", "-p", "8000:8000",
    "-v", vm + "/hf-cache:/root/.cache/huggingface",
    "--env-file", vm + "/vllm.env", "-e", "HF_HUB_DISABLE_XET=1",
    "vllm/vllm-openai:v0.30.0",
    "Qwen/Qwen3.8-27B-FP8", "--host", "0.0.0.0", "--port", "8000",
    "--max-model-len", "250000", "--kv-cache-dtype", "fp8", "--gpu-memory-utilization", "0.9",
    "--reasoning-parser", "qwen3",
    "--default-chat-template-kwargs", '{"reasoning_effort": "low"}',
    "--enable-auto-tool-choice", "--tool-call-parser", "qwen3_xml",
    "--speculative-config", '{"method": "mtp", "num_speculative_tokens": 3}',
]
assert docker_run(calls) == expected, docker_run(calls)
assert ["pull", "vllm/vllm-openai:v0.30.0"] in [c["args"] for c in calls if c["cmd"] == "docker"]
assert not [c for c in calls if c["cmd"] in ("ufw", "openssl", "apt-get")], "stage A has no TLS or firewall"
# The key reaches vLLM through a file only this user can read, never the log.
env_file = os.path.join(vm, "vllm.env")
assert open(env_file).read() == "VLLM_API_KEY=%s\n" % KEY
assert stat.S_IMODE(os.stat(env_file).st_mode) == 0o600, oct(os.stat(env_file).st_mode)
log = open(os.path.join(vm, "start.log")).read()
assert "start: mode=http port=8000" in log and "container started" in log, log
assert "NVIDIA A100-SXM4-80GB, 580.82.07" in log, log
for text in (log, proc.stdout, proc.stderr, json.dumps(calls)):
    assert KEY not in text

# 4. A host driver too old for CUDA 13 stops before anything is pulled.
proc, vm, calls = run_script(script_a, driver="550.54.15")
assert proc.returncode != 0
assert "FATAL: driver 550.54.15 is too old for the CUDA 13 image" in proc.stdout, proc.stdout
assert not [c for c in calls if c["cmd"] == "docker"], calls

# 5. Stage B: certificate, firewall, only 8443 published, TLS flags.
proc, vm, calls = run_script(script_b)
assert proc.returncode == 0, proc.stdout + proc.stderr
ufw = [c["args"] for c in calls if c["cmd"] == "ufw"]
assert ufw[0] == ["--force", "reset"], "provider rules are cleared first: %s" % ufw
assert ufw[1] == ["default", "deny", "incoming"] and ufw[2] == ["default", "allow", "outgoing"], ufw
assert ["allow", "22/tcp"] in ufw and ["allow", "2222/tcp"] in ufw, "SSH stays reachable: %s" % ufw
assert ["allow", "8443/tcp"] in ufw, ufw
assert ufw.index(["--force", "enable"]) > ufw.index(["allow", "8443/tcp"]), "rules before enabling"
assert not [a for a in ufw if any("8000" in x for x in a)], "8000 is never opened"
req = next(c["args"] for c in calls if c["cmd"] == "openssl" and c["args"][:1] == ["req"])
assert req[req.index("-keyout") + 1] == vm + "/tls/key.pem" and req[req.index("-out") + 1] == vm + "/tls/cert.pem"
assert stat.S_IMODE(os.stat(vm + "/tls/key.pem").st_mode) == 0o600
run = docker_run(calls)
assert run[run.index("-p") + 1] == "8443:8443" and run.count("-p") == 1, run
assert vm + "/tls:/tls:ro" in run, run
serve = run[run.index("vllm/vllm-openai:v0.30.0") + 1:]
assert serve == ["Qwen/Qwen3.8-27B-FP8", "--host", "0.0.0.0", "--port", "8443"] + sd.vllm_flags() + \
    ["--ssl-keyfile", "/tls/key.pem", "--ssl-certfile", "/tls/cert.pem"], serve
log = open(os.path.join(vm, "start.log")).read()
assert "sha256 Fingerprint=AA:BB:CC" in log and "firewall: deny incoming except SSH and 8443" in log, log
assert KEY not in log + proc.stdout + proc.stderr

# 6. The vLLM flags: one GPU is exactly the list checked against deploy.py at
#    68cff7e (phase 4 task 1.2); two GPUs add only the split, at the end.
PHASE4_FLAGS = [
    "--max-model-len", "250000", "--kv-cache-dtype", "fp8", "--gpu-memory-utilization", "0.9",
    "--reasoning-parser", "qwen3", "--default-chat-template-kwargs", '{"reasoning_effort": "low"}',
    "--enable-auto-tool-choice", "--tool-call-parser", "qwen3_xml",
    "--speculative-config", '{"method": "mtp", "num_speculative_tokens": 3}',
]
assert sd.vllm_flags() == PHASE4_FLAGS and sd.vllm_flags(1) == PHASE4_FLAGS, sd.vllm_flags()
assert sd.vllm_flags(2) == PHASE4_FLAGS + ["--tensor-parallel-size", "2"], sd.vllm_flags(2)

# 7. One GPU: the script is byte for byte the phase 4 script (saved before this change).
for https, name in ((False, "http"), (True, "https")):
    golden = open(os.path.join(HERE, "data", "startup_script_phase4_%s.sh" % name)).read()
    assert sd.startup_script(KEY, https=https) == golden, name
    assert sd.startup_script(KEY, https=https, tensor_parallel=1) == golden, name

# 8. Two GPUs, stage A: GPU check passes, topology logged, --ipc=host, the split passed.
script_tp = sd.startup_script(KEY, https=False, tensor_parallel=2)
script_tp_b = sd.startup_script(KEY, https=True, tensor_parallel=2)
for s in (script_tp, script_tp_b):
    check = subprocess.run(["bash", "-n"], input=s, capture_output=True, text=True)
    assert check.returncode == 0, check.stderr
proc, vm, calls = run_script(script_tp, gpus=2)
assert proc.returncode == 0, proc.stdout + proc.stderr
run = docker_run(calls)
assert run == [
    "run", "-d", "--name", "qwen38", "--restart", "on-failure:3", "--gpus", "all",
    "--ipc=host", "-p", "8000:8000",
    "-v", vm + "/hf-cache:/root/.cache/huggingface",
    "--env-file", vm + "/vllm.env", "-e", "HF_HUB_DISABLE_XET=1",
    "vllm/vllm-openai:v0.30.0",
    "Qwen/Qwen3.8-27B-FP8", "--host", "0.0.0.0", "--port", "8000",
] + PHASE4_FLAGS + ["--tensor-parallel-size", "2"], run
assert "--shm-size" not in run, run
log = open(os.path.join(vm, "start.log")).read()
assert "start: mode=http port=8000 image=vllm/vllm-openai:v0.30.0 tensor_parallel=2" in log, log
assert "GPUs: 2, tensor parallel 2; topology:" in log and "GPU0     X      PHB" in log, log
assert ["topo", "-m"] in [c["args"] for c in calls if c["cmd"] == "nvidia-smi"], calls
assert KEY not in log + proc.stdout + proc.stderr

# 9. Two GPUs requested, one found: stop before pulling or starting anything.
proc, vm, calls = run_script(script_tp, gpus=1)
assert proc.returncode != 0
assert "FATAL: 2 GPUs requested, 1 found" in proc.stdout, proc.stdout
assert not [c for c in calls if c["cmd"] == "docker"], calls

# 10. Two GPUs, stage B: the firewall and TLS are unchanged, the split comes after
#     the shared flags and before the TLS flags.
proc, vm, calls = run_script(script_tp_b, gpus=2)
assert proc.returncode == 0, proc.stdout + proc.stderr
run = docker_run(calls)
assert "--ipc=host" in run and run[run.index("-p") + 1] == "8443:8443" and run.count("-p") == 1, run
serve = run[run.index("vllm/vllm-openai:v0.30.0") + 1:]
assert serve == ["Qwen/Qwen3.8-27B-FP8", "--host", "0.0.0.0", "--port", "8443"] + PHASE4_FLAGS + \
    ["--tensor-parallel-size", "2", "--ssl-keyfile", "/tls/key.pem", "--ssl-certfile", "/tls/cert.pem"], serve
ufw = [c["args"] for c in calls if c["cmd"] == "ufw"]
assert ufw[0] == ["--force", "reset"] and ["allow", "8443/tcp"] in ufw, ufw

print("ok: create request, script syntax, stage A and B commands, driver check,"
      " flags and scripts for 1 and 2 GPUs, GPU-count check")
