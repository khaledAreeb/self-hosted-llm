"""Runs every shadeform_deploy.py command against a local fake Shadeform API
and a fake vLLM: up (normal, no capacity, never ready, Ctrl-C, VM error,
HTTPS), down, status, reap, and the secret handling. No network, no cost.

    python3 tests/test_shadeform_lifecycle.py
"""

import base64
import datetime
import hashlib
import json
import os
import re
import signal
import ssl
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
TOOL = os.path.join(ROOT, "shadeform_deploy.py")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
from shadeform_fakes import FakeShadeform, FakeVLLM, closed_port  # noqa: E402
import shadeform_deploy as sd  # noqa: E402

SF_KEY = "sf-dummy-key-7c1e9a3f"
VK = "vllm-dummy-key-4b2d8f6e1a9c"
TYPES = json.load(open(os.path.join(HERE, "data", "shadeform_types_sample.json")))["instance_types"]
OUTPUTS = []        # every line the tool printed, checked for secrets at the end


def workdir(vllm_key=VK):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, ".env"), "w") as f:
        f.write("SHADEFORM_API_KEY=%s\n" % SF_KEY + ("VLLM_API_KEY=%s\n" % vllm_key if vllm_key else ""))
    return d


def tool_env(api_url, d, **ports):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("SHADEFORM_") and k != "VLLM_API_KEY"}
    env.update({
        "SHADEFORM_API_URL": api_url,
        "SHADEFORM_ENV_FILE": os.path.join(d, ".env"),
        "SHADEFORM_POLL_SECONDS": "0.05",
        "SHADEFORM_START_LIMIT_SECONDS": "20",
        "SHADEFORM_DELETE_CONFIRM_SECONDS": "5",
    })
    for vm_port, local in ports.items():
        env["SHADEFORM_TEST_PORT_%s" % vm_port.lstrip("p")] = str(local)
    return env


def run(args, env, d, timeout=60):
    p = subprocess.run([sys.executable, TOOL] + args, env=env, cwd=d, capture_output=True,
                       text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    OUTPUTS.append(p.stdout + p.stderr)
    return p.returncode, p.stdout + p.stderr


def name_in(minutes):
    t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    return sd.instance_name(t.replace(second=0, microsecond=0))


def fresh(**kw):
    api = FakeShadeform(SF_KEY, TYPES, **kw)
    return api, api.start()


# --- up: the normal path ----------------------------------------------------
api, url = fresh()
vllm = FakeVLLM(VK)
d = workdir()
rc, out = run(["up", "--hours", "1", "--yes"], tool_env(url, d, p8000=vllm.start()), d)
assert rc == 0, out
assert "READY after" in out and "'ready'" in out, out
assert "API Base            http://127.0.0.1:8000/v1" in out, out
assert "WARNING: plain HTTP is NOT encrypted" in out, out
assert "the VLLM_API_KEY value in .env (not printed here)" in out, out
[create] = api.creates()
assert create["name"].startswith("qwen38-until-") and create["launch_configuration"]["type"] == "script"
assert create["auto_delete"]["date_threshold"].endswith("Z") and create["auto_delete"]["spend_threshold"] == "1.52"
assert (create["cloud"], create["region"]) == ("massedcompute", "beltsville-usa-1"), create  # cheapest first
assert api.deletes() == [], "a VM that answered is left running"
assert ("GET", "/v1/models", True) in vllm.requests and ("GET", "/v1/models", False) in vllm.requests
assert ("POST", "/v1/chat/completions", True) in vllm.requests
iid = next(iter(api.instances))
assert "python3 shadeform_deploy.py down %s" % iid in out, out

# status, then down with no id: the tool's only instance is deleted and confirmed
rc, out = run(["status"], tool_env(url, d), d)
assert rc == 0 and iid in out and "$1.38/hr" in out, out
assert "time left 1h00m" in out or "time left 59m" in out, out
rc, out = run(["down"], tool_env(url, d), d)
assert rc == 0 and api.deletes() == [iid] and "billing has stopped" in out, out
assert api.instances[iid]["status"] == "deleting"
rc, out = run(["status"], tool_env(url, d), d)
assert iid in out and "status deleting" in out, out                 # still listed while deleting
rc, out = run(["down"], tool_env(url, d), d)
assert rc == 0 and "Nothing to delete" in out, out
api.stop(); vllm.stop()

# --- up: no capacity on the first offer, so the next one is tried -------------
api, url = fresh(capacity_failures=1)
vllm = FakeVLLM(VK)
d = workdir()
rc, out = run(["up", "--hours", "1", "--yes"], tool_env(url, d, p8000=vllm.start()), d)
assert rc == 0, out
first, second = api.creates()
assert (first["cloud"], first["region"]) == ("massedcompute", "beltsville-usa-1")
assert (second["cloud"], second["region"]) == ("massedcompute", "desmoines-usa-1"), second
assert "refused the create (HTTP 400" in out and "trying the next offer" in out, out
api.stop(); vllm.stop()

# --- up --gpu H100: the cheapest H100, not the cheapest GPU -------------------
api, url = fresh()
vllm = FakeVLLM(VK)
d = workdir()
rc, out = run(["up", "--hours", "1", "--yes", "--gpu", "H100"], tool_env(url, d, p8000=vllm.start()), d)
assert rc == 0, out
[create] = api.creates()
assert (create["cloud"], create["region"], create["shade_instance_type"]) == ("scaleway", "paris-france-1", "H100"), create
assert create["os"] == "ubuntu24.04_cuda13.0_shade_os" and create["auto_delete"]["spend_threshold"] == "3.63", create
rc, out = run(["up", "--hours", "1", "--yes", "--gpu", "B200"], tool_env(url, d), d)
assert rc == 1 and "no usable offer right now for those filters" in out and len(api.creates()) == 1, out
api.stop(); vllm.stop()

# ... and no offer has capacity: three tries, then stop with nothing created
api, url = fresh(capacity_failures=10)
d = workdir()
rc, out = run(["up", "--hours", "1", "--yes"], tool_env(url, d, p8000=closed_port()), d)
assert rc == 1 and len(api.creates()) == 3 and api.instances == {}, out
assert "no offer accepted the create request (tried 3). Nothing was created." in out, out
api.stop()

# --- up: the model never answers, so the VM is deleted ----------------------
api, url = fresh()
d = workdir()
env = tool_env(url, d, p8000=closed_port())
env["SHADEFORM_START_LIMIT_SECONDS"] = "1.5"
rc, out = run(["up", "--hours", "1", "--yes"], env, d)
[iid] = api.instances
assert rc == 1 and "not ready after" in out, out
assert "last stage: waiting for vLLM on port 8000" in out, out
assert api.deletes()[:1] == [iid] and api.instances[iid]["status"] == "deleting", out
assert "billing has stopped" in out, out
api.stop()

# --- up: Ctrl-C (and kill) while waiting deletes the VM ----------------------
for sig, label in ((signal.SIGINT, "Ctrl-C"), (signal.SIGTERM, "kill")):
    api, url = fresh()
    d = workdir()
    proc = subprocess.Popen([sys.executable, TOOL, "up", "--hours", "1", "--yes"],
                            env=tool_env(url, d, p8000=closed_port()), cwd=d, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    end = time.time() + 20
    while time.time() < end and not any(i.get("info_calls_active", 0) >= 3 for i in api.instances.values()):
        time.sleep(0.05)
    proc.send_signal(sig)
    out, _ = proc.communicate(timeout=30)
    OUTPUTS.append(out)
    [iid] = api.instances
    assert proc.returncode == 130 and "FAILED: interrupted" in out, (label, out)
    assert api.deletes()[:1] == [iid] and api.instances[iid]["status"] == "deleting", (label, out)
    api.stop()

# --- up: the VM reports an error ---------------------------------------------
api, url = fresh(boot=("creating", "pending_provider", "error"))
d = workdir()
rc, out = run(["up", "--hours", "1", "--yes"], tool_env(url, d, p8000=closed_port()), d)
[iid] = api.instances
assert rc == 1 and "Shadeform reports status 'error'" in out, out
assert api.deletes()[:1] == [iid] and "billing has stopped" in out, out
api.stop()

# --- up: an endpoint that answers WITHOUT the key is not accepted -----------
api, url = fresh()
vllm = FakeVLLM(VK, open_without_key=True)
d = workdir()
rc, out = run(["up", "--hours", "1", "--yes"], tool_env(url, d, p8000=vllm.start()), d)
assert rc == 1 and "SECURITY: the endpoint did not refuse a request without the key" in out, out
assert len(api.deletes()) >= 1, out
api.stop(); vllm.stop()

# --- up: refusals that create nothing ----------------------------------------
api, url = fresh()
d = workdir()
rc, out = run(["up", "--yes"], tool_env(url, d), d)                     # no --hours
assert rc == 2 and "--hours" in out and api.creates() == [], out
rc, out = run(["up", "--hours", "0", "--yes"], tool_env(url, d), d)
assert rc == 1 and "--hours must be more than 0" in out and api.creates() == [], out
rc, out = run(["up", "--hours", "1", "--yes", "--region", "nowhere"], tool_env(url, d), d)
assert rc == 1 and "no usable offer right now for those filters" in out and api.creates() == [], out
rc, out = run(["up", "--hours", "1"], tool_env(url, d), d)              # no terminal, no --yes
assert rc == 1 and "this creates a paid VM" in out and api.creates() == [], out
api.stop()

# --- up --https: TLS readiness, fingerprint, plain HTTP and port 8000 closed --
tmp = tempfile.mkdtemp()
cert, key = os.path.join(tmp, "cert.pem"), os.path.join(tmp, "key.pem")
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                "-subj", "/CN=qwen38-test", "-keyout", key, "-out", cert],
               check=True, capture_output=True)
want = hashlib.sha256(ssl.PEM_cert_to_DER_cert(open(cert).read())).hexdigest().upper()
want = ":".join(want[i:i + 2] for i in range(0, len(want), 2))
api, url = fresh()
vllm = FakeVLLM(VK, tls=(cert, key))
d = workdir()
rc, out = run(["up", "--hours", "1", "--yes", "--https"],
              tool_env(url, d, p8443=vllm.start(), p8000=closed_port()), d)
assert rc == 0, out
assert "API Base            https://127.0.0.1:8443/v1" in out, out
assert "ssl_verify          false" in out and "certificate SHA-256 %s" % want in out, out
assert "HTTPS only: plain HTTP is refused and port 8000 is closed" in out, out
assert "WARNING: plain HTTP" not in out, out
assert api.deletes() == [], out
api.stop()

# ... and if port 8000 still answers, the start counts as failed and is deleted
api, url = fresh()
open_8000 = FakeVLLM(VK)
d = workdir()
rc, out = run(["up", "--hours", "1", "--yes", "--https"],
              tool_env(url, d, p8443=vllm.server.server_port, p8000=open_8000.start()), d)
assert rc == 1 and "SECURITY: port 8000 accepts connections" in out and len(api.deletes()) >= 1, out
api.stop(); vllm.stop(); open_8000.stop()

# --- down / status / reap with other people's instances on the account -------
api, url = fresh()
d = workdir()
expired = api.add(name_in(-30), created_minutes_ago=90)
current = api.add(name_in(120), created_minutes_ago=5)
theirs = api.add("team-prod-llm")
look_alike = api.add("someone-until-20200101T0000Z")
unreadable = api.add("qwen38-until-garbage")
env = tool_env(url, d)

rc, out = run(["status"], env, d)
assert rc == 0 and expired in out and current in out and unreadable in out, out
assert "OVERDUE by 30m (run reap)" in out or "OVERDUE by 29m (run reap)" in out, out
assert "deadline unreadable" in out and "cost so far $0.42" in out, out
assert theirs not in out and look_alike not in out, "other instances are not shown"

rc, out = run(["down"], env, d)                                          # several: refuse
assert rc == 1 and "say which one" in out and api.deletes() == [], out
rc, out = run(["down", theirs], env, d)                                  # not ours: refuse
assert rc == 1 and "refusing" in out and api.deletes() == [], out

rc, out = run(["reap"], env, d)
assert rc == 0 and api.deletes() == [expired], (api.deletes(), out)
assert "1 deleted, 2 still within their deadline" in out, out
assert "unreadable deadline" in out, out
assert all(api.instances[i]["status"] == "active" for i in (current, theirs, look_alike, unreadable))
rc, out = run(["reap"], env, d)                                          # nothing left to do
assert rc == 0 and api.deletes() == [expired] and "0 deleted" in out, out

rc, out = run(["down", current], env, d)                                 # by id
assert rc == 0 and api.deletes() == [expired, current], out
api.stop()

# --- tensor parallel: refused values, the 2-GPU path, a wrong machine ----------
MULTI = json.load(open(os.path.join(HERE, "data", "shadeform_types_multigpu_sample.json")))["instance_types"]
api = FakeShadeform(SF_KEY, MULTI)
url = api.start()
d = workdir()
rc, out = run(["up", "--hours", "1", "--yes", "--tensor-parallel", "3"], tool_env(url, d), d)
# Python 3.12+ argparse quotes the rejected value ('3'); older versions don't.
assert rc == 2 and ("invalid choice: 3" in out or "invalid choice: '3'" in out) and api.creates() == [], out
rc, out = run(["up", "--hours", "1", "--yes", "--tensor-parallel", "2", "--gpu", "B200"], tool_env(url, d), d)
assert rc == 1 and "no usable offer right now for those filters" in out and api.creates() == [], out
vllm = FakeVLLM(VK)
rc, out = run(["up", "--hours", "1", "--yes", "--tensor-parallel", "2", "--gpu", "A100"],
              tool_env(url, d, p8000=vllm.start()), d)
assert rc == 0, out
[create] = api.creates()
assert (create["cloud"], create["shade_instance_type"]) == ("massedcompute", "A100_80Gx2"), create
assert create["auto_delete"]["spend_threshold"] == "2.97", create["auto_delete"]   # 1 h x $2.70 x 1.1
script = base64.b64decode(create["launch_configuration"]["script_configuration"]["base64_script"]).decode()
assert "--tensor-parallel-size 2" in script and "--ipc=host" in script and "--shm-size" not in script
assert "GPUs      2 x A100_80G (80 GB each), tensor parallel 2, link: PCIe, no NVLink (per Shadeform)" in out, out
assert "$2.70/hr for the whole VM" in out and "all 2 in use" in out and "READY after" in out, out
assert api.deletes() == [], out
api.stop(); vllm.stop()

api = FakeShadeform(SF_KEY, MULTI, report_gpus=1)     # Shadeform hands over a 1-GPU machine
url = api.start()
d = workdir()
began = time.time()
rc, out = run(["up", "--hours", "1", "--yes", "--tensor-parallel", "2"], tool_env(url, d, p8000=closed_port()), d)
[iid] = api.instances
assert rc == 1 and "Shadeform's VM has 1 GPU(s), 2 were requested" in out, out
assert api.deletes()[:1] == [iid] and "billing has stopped" in out, out
assert time.time() - began < 10, "deleted within seconds, not after the start limit"
api.stop()

api = FakeShadeform(SF_KEY, MULTI)
url = api.start()
d = workdir()
rc, out = run(["offers", "--tensor-parallel", "2"], tool_env(url, d), d)
assert rc == 0 and "2 GPUs on one VM" in out and "A100_80Gx2" in out and "A6000x2" not in out, out
assert "newest host CUDA is 12.2" in out and "PCIe, no NVLink" in out, out
rc, out = run(["offers"], tool_env(url, d), d)                        # the default: one GPU
assert rc == 0 and "Usable now (1 GPU" in out and "A100_80Gx2" not in out and "link" not in out, out
api.stop()

# --- offers through the CLI, with the key and without ------------------------
api, url = fresh()
d = workdir()
rc, out = run(["offers"], tool_env(url, d), d)
assert rc == 0 and "1.38  A100_sxm4_80G_DGX  massedcompute   beltsville-usa-1" in out, out
assert "newest host CUDA is 12.4" in out, out
os.remove(os.path.join(d, ".env"))
rc, out = run(["offers", "--region", "france"], tool_env(url, d), d)
assert rc == 0 and "paris-france-1" in out and "houston" not in out, out
api.stop()

# --- secrets: a missing VLLM_API_KEY is generated, saved, never printed ------
api, url = fresh()
d = workdir(vllm_key=None)
env_path = os.path.join(d, ".env")


def generated_key():
    return re.search(r"VLLM_API_KEY=(\S+)", open(env_path).read()).group(1)


vllm = FakeVLLM(generated_key)
before = set(os.listdir(d))
env = tool_env(url, d, p8000=vllm.start())
rc, out = run(["up", "--hours", "1", "--yes"], env, d)
assert rc == 0 and "Generated a new VLLM_API_KEY and saved it to" in out, out
new_key = generated_key()
assert len(new_key) >= 32 and new_key not in out, out
assert open(env_path).read().count("VLLM_API_KEY=") == 1
script = base64.b64decode(
    api.creates()[0]["launch_configuration"]["script_configuration"]["base64_script"]).decode()
assert "VLLM_API_KEY=" + new_key in script, "the VM gets the generated key"
rc, out = run(["down"], env, d)
rc, out = run(["up", "--hours", "1", "--yes"], env, d)                  # reused, not regenerated
assert rc == 0 and "Generated" not in out and open(env_path).read().count("VLLM_API_KEY=") == 1, out
run(["down"], env, d)
assert set(os.listdir(d)) == before, "the tool writes no file other than .env: %s" % os.listdir(d)
OUTPUTS.append(open(env_path).read().replace(SF_KEY, "").replace(new_key, ""))
api.stop(); vllm.stop()

# A malformed VLLM_API_KEY is refused before anything is created.
api, url = fresh()
d = workdir(vllm_key="has spaces in it, not ok")
rc, out = run(["up", "--hours", "1", "--yes"], tool_env(url, d), d)
assert rc == 1 and "VLLM_API_KEY in .env must be" in out and api.creates() == [], out
api.stop()

# No secret ever appeared in anything the tool printed.
for text in OUTPUTS:
    assert SF_KEY not in text and VK not in text, text

print("ok: up (normal, capacity, never ready, Ctrl-C, kill, error, open endpoint, refusals, https),"
      " tensor parallel (refusals, 2-GPU path, wrong machine), down, status, reap, offers, secrets")
