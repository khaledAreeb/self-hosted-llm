# shadeform_deploy.py — complete code guide

Line numbers refer to `shadeform_deploy.py` as of this writing (1100 lines).

---

## 1. What the script is

A single-file, standard-library-only command line tool that **rents a GPU VM from Shadeform, starts vLLM in Docker on it serving `Qwen/Qwen3.8-27B-FP8`, waits until the model really answers, and later deletes the VM**.

The central problem it solves: Shadeform has **no scale-to-zero**. A VM bills from the moment it is created until it is deleted. So almost all of the code that is not "start vLLM" is about *making sure the VM gets deleted*:

- every VM gets a mandatory deadline (`--hours`),
- the deadline is enforced twice by Shadeform itself (date + spend threshold),
- the deadline is also written into the VM's **name**, so `reap` can enforce it a third time,
- if `up` fails or is interrupted, it deletes the VM it just made,
- deletion is confirmed with Shadeform, not assumed.

### Big picture

```
 your laptop (this script)                    Shadeform API              the VM (GPU box)
 ─────────────────────────                    ─────────────              ────────────────
 offers ──GET /instances/types──────────────▶  catalogue
 up     ──POST /instances/create + script───▶  creates VM ─────────────▶ boots, runs startup script:
        ──poll GET /instances/{id}/info─────▶  status                      check driver, (firewall),
        ──GET  :8000|8443/v1/models────────────────────────────────────▶   docker pull, docker run vLLM
        ──POST :8000|8443/v1/chat/completions──────────────────────────▶   model answers → READY
 status ──GET /instances────────────────────▶  list (filtered by name prefix)
 down   ──POST /instances/{id}/delete───────▶  deleting → billing stops
 reap   ──same as down, for expired names
```

The script never SSHes into the VM. Everything it does to the VM is (a) hand Shadeform a bash script at create time and (b) talk to vLLM over HTTP(S) afterwards.

---

## 2. Commands

| Command | Cost | What it does |
|---|---|---|
| `offers` | free | List GPU offers that can run the model, cheapest first, split into *usable* and *not usable* (with reason). |
| `up --hours N` | **paid** | Pick the cheapest usable offer, create the VM, wait until the model gives a real answer, print the gateway settings. |
| `status` | free | List this tool's VMs: id, name, provider/region, IP, state, price, cost so far, time left. |
| `down [ID]` | stops billing | Delete this tool's VM and wait for Shadeform to confirm. |
| `reap` | stops billing | Delete every tool VM whose deadline has passed (meant for cron). |

### Flags

- Filters (on `offers` and `up`): `--region`, `--gpu`, `--cloud`, `--tensor-parallel N`. `--region/--gpu/--cloud` can be repeated or comma-separated (`_filters`, line 426).
- `up` only:
  - `--hours` (required, float, `0 < hours ≤ 24`),
  - `--https` (TLS on 8443 + firewall),
  - `--yes` (skip the confirmation prompt),
  - `--ssh-key-id ID` (otherwise the account's default key).
- `down` takes an optional positional instance `id` (required only when several are running).

### Exit codes

`0` success · `1` any expected failure (`Fail`), unreachable Shadeform, cancelled prompt, or deletion not confirmed · `130` interrupted (Ctrl-C).

---

## 3. Map of the file

| Lines | Section | Purpose |
|---|---|---|
| 1–25 | Docstring | Usage, secrets, pointer to the design doc. |
| 27–44 | Imports | Standard library only. |
| 46–101 | Serving settings | The vLLM model/flags, and `vllm_flags()`. |
| 104–147 | VM settings | GPU memory floor, CUDA floor, name prefix, ports, timing limits, env-var overrides. |
| 150–233 | Output and secrets | `Fail`, `redact`, `say`, `.env` reading, API-key handling. |
| 236–330 | Shadeform API | `api()`, `/info`, `/instances`, tool-instance filtering, `delete_and_confirm`. |
| 333–455 | Offers | CUDA parsing, `split_offers`, `cmd_offers`. |
| 458–568 | Startup script | `startup_script()` — generates the VM's bash. |
| 571–944 | Up | Deadlines/names, create request, VM probing, `wait_until_ready`, `create_vm`, `cmd_up`. |
| 947–1030 | Status / down / reap | The three management commands. |
| 1033–1100 | CLI | `build_parser`, `main`. |

---

## 4. Section-by-section walkthrough

### 4.1 Serving settings (lines 46–101)

Constants that become vLLM command-line flags. Each comment records *why*:

| Constant | Value | Meaning |
|---|---|---|
| `MODEL_ID` | `Qwen/Qwen3.8-27B-FP8` | Publisher's FP8 checkpoint (~28 GB). Downloaded by vLLM on **every** VM start (nothing persists between VMs). |
| `MAX_MODEL_LEN` | 250 000 | Max tokens for one request. Just below the 262 144 native limit so no rope scaling is needed. It's a cap, not a reservation. |
| `KV_CACHE_DTYPE` | `fp8` | Halves KV-cache memory vs BF16 → more concurrent long prompts. |
| `GPU_MEMORY_UTILIZATION` | 0.90 | Fraction of GPU memory vLLM may take. |
| `REASONING_PARSER` | `qwen3` | Separates thinking (`reasoning` field) from the answer (`content`). |
| `CHAT_TEMPLATE_KWARGS` | `{"reasoning_effort": "low"}` | The default "xhigh" burned whole token budgets thinking and returned nothing. Callers can override per request. |
| `TOOL_CALL_PARSER` | `qwen3_xml` | Structured tool calls for agents (Copilot, OpenCode), with `--enable-auto-tool-choice`. |
| `SPECULATIVE_CONFIG` | MTP, 3 tokens | Multi-token prediction, ~2.8× faster decoding, measured to hold under load. |
| `VLLM_IMAGE` | `vllm/vllm-openai:v0.30.0` | Pinned container. Built on CUDA 13.0 → host driver must be ≥ 580. |

**`vllm_flags(tensor_parallel=1)`** returns the flag list. For 1 GPU it's the base list only. For >1 it *appends* `--tensor-parallel-size N` at the end, so the single-GPU path stays byte-identical to what was verified against `deploy.py`.

### 4.2 VM settings (lines 104–147)

- `MIN_GPU_MEMORY_GB = 80` — every GPU in an offer must have ≥ 80 GB (28.9 GiB weights + KV cache for 250K context). Applies per GPU, even when split.
- `TENSOR_PARALLEL_CHOICES = (1, 2, 4, 8)` — vLLM needs the split to divide the attention heads; powers of two are safe. Only 1 and 2 are actually tested.
- `MIN_HOST_CUDA = (13, 0)` — a host driver older than the image's CUDA would fail to start the container, costing money and 15+ minutes. So offers are screened *before* creating anything.
- `NAME_PREFIX = "qwen38-until-"` — **the safety boundary**. The Shadeform account is a shared company workspace; the tool only lists/deletes instances whose name starts with this.
- `HTTP_PORT = 8000` (stage A, plain HTTP) and `HTTPS_PORT = 8443` (stage B, TLS).
- `MAX_CREATE_ATTEMPTS = 3` (offers can disappear between listing and creating), `MAX_HOURS = 24` (typo guard), `SPEND_MARGIN = 1.10`.
- `CONTAINER = "qwen38"`, `VM_DIR = "/opt/qwen38"` (start log, HF cache, key file, TLS files on the VM).
- **Environment overrides** (mostly for tests): `SHADEFORM_API_URL`, `SHADEFORM_POLL_SECONDS` (15), `SHADEFORM_START_LIMIT_SECONDS` (2400 = 40 min), `SHADEFORM_DELETE_CONFIRM_SECONDS` (300), `SHADEFORM_ENV_FILE` (`.env` beside the script).
- `reach_port(port)` — test seam: `SHADEFORM_TEST_PORT_8000=54321` makes the script connect to a local fake vLLM instead of the real port. In normal use it returns the port unchanged.

### 4.3 Output and secrets (lines 150–233)

- `Fail` — exception for *expected* failures; `main()` prints it as `ERROR: …` and exits 1.
- `_SECRETS` is a set of every secret value the process has loaded. **`say()` is the only way anything is printed**, and it runs `redact()`, which replaces each secret with `<hidden>` and any base64-looking run of 200+ characters with `<base64 hidden>` (so the encoded startup script, which contains the vLLM key, can't leak into an error message).
- `short(body, 300)` truncates API responses for error messages.
- `read_env_file()` — tiny `.env` parser: skips blanks/comments, accepts `export NAME=…`, strips surrounding quotes.
- `secret(name)` — environment variable first, then `.env`; registers the value for redaction.
- `shadeform_key()` — requires `SHADEFORM_API_KEY` or raises a helpful `Fail`.
- `vllm_key()` — the key **vLLM will demand from clients**:
  - If `VLLM_API_KEY` exists it must match `[A-Za-z0-9._~+/=-]{16,}` (it is later put on a shell line, so no spaces/quotes).
  - If missing, a 32-byte `token_urlsafe` is generated and **appended to `.env`** (adding a newline first if the file lacked one; a brand-new file is `chmod 600`). It prints that it did so, without showing the value, and tells you to give the gateway the same value.

### 4.4 Shadeform API helpers (lines 236–330)

- `api(method, path, key, body, timeout)` — one call using `urllib`. Sends `X-API-KEY`, JSON body if given. Returns `(status, parsed_json_or_text)`. HTTP errors (4xx/5xx) are *returned*, not raised; network failures raise `URLError`/`OSError` (callers decide what that means).
- `check_auth(status)` — 401/403 → `Fail("Shadeform refused the API key")`.
- `instance_info(key, iid)` — `/instances/{id}/info`; `None` on 404, `OSError` on any other non-200.
- `all_instances(key)` — `/instances`: every non-deleted instance, including ones in `deleting`.
- `tool_instances(key)` — `all_instances` filtered by `NAME_PREFIX`.
- `_ignore_interrupts()` — sets SIGINT/SIGTERM/SIGHUP to ignore and returns the old handlers so they can be restored.
- **`delete_and_confirm(key, iid)`** — the most important safety function:
  1. Ignores Ctrl-C / terminal close / kill for its whole duration (a half-finished deletion = a VM billing forever).
  2. Loops up to `DELETE_CONFIRM_SECONDS` (5 min): sends `POST …/delete` (re-sent at most every 30 s), then lists instances and reads the state.
  3. State `deleting`, `deleted`, or *absent* ⇒ prints "billing has stopped" and returns `True`. (Shadeform stops billing at `deleting`.)
  4. Network errors are printed and retried. If never confirmed, it prints a loud WARNING with the retry command and returns `False`.
  5. Always restores the signal handlers (`finally`).

### 4.5 Offers (lines 333–455)

`host_cuda(os_name)` extracts `(13, 0)` from OS image names like `ubuntu_22_04_cuda13.0_shade_os`.

**`split_offers(types, regions, clouds, gpus, tensor_parallel)`** turns the `/instances/types` catalogue into `(usable, not_usable)`:

1. Skip a type unless `num_gpus == tensor_parallel` **exactly** and `vram_per_gpu_in_gb ≥ 80`.
2. Apply `--cloud` (exact match) and `--gpu` (substring of "gpu_type + instance_type", case-insensitive).
3. From the type's `os_options`, keep those with a CUDA version; sort by `(cuda version, is a shade_os image, name)` and take the last → **the newest CUDA image, preferring `shade_os` on ties**. This image name is what gets sent as `os` on create.
4. For each *availability* entry that is `available` **and** `on_demand` (spot is ignored), apply the `--region` substring filter and build a row (cloud, type, region, place name, GPU, VRAM, price in cents, OS image, GPU count, link description).
5. Row is **usable** if the best image's CUDA ≥ 13.0, otherwise **not usable** with a reason (`newest host CUDA is 12.x` / `no CUDA image offered`).
6. Both lists are sorted by `(price, cloud, region)`; a missing price sorts last.

`link_text(conf)` — "NVLink", or e.g. "PCIe, no NVLink" (relevant when splitting across GPUs). `gpu_summary()` formats the multi-GPU plan line. `fetch_types()` calls `/instances/types` (auth optional for listing). `_offer_line()` formats one table row (extra "link" column only in multi-GPU listings, so the 1-GPU output is unchanged).

`cmd_offers` prints the usable table then the not-usable table. It says `(none right now; up would create nothing)` if the usable list is empty.

### 4.6 The startup script (lines 458–568)

`startup_script(api_key, https, tensor_parallel)` builds the **bash script Shadeform runs once the VM is active**, as a Python list of lines joined with newlines. Every vLLM argument passes through `shlex.quote` so JSON values like `{"method": "mtp", …}` arrive intact.

What the generated script does, in order:

1. `set -euo pipefail`; `DIR=/opt/qwen38` (overridable via `QWEN38_DIR`); `SUDO` is empty if root else `sudo -n`; create + chown the dir.
2. Log everything: `exec > >(tee -a "$LOG") 2>&1` → `/opt/qwen38/start.log`; a `step()` helper adds UTC timestamps; an `ERR` trap logs `FATAL: line N failed`.
3. **Driver gate**: reads `nvidia-smi` driver version; if the major is < 580, logs FATAL and exits (the CUDA 13 image can't run).
4. *(tensor parallel only)* count GPUs with `nvidia-smi`; exit if fewer than requested; log `nvidia-smi topo -m` (how GPUs are linked).
5. **Key file**: `umask 077`, write `VLLM_API_KEY=…` to `$DIR/vllm.env` (mode 600), restore `umask 022`, create `$DIR/hf-cache`.
6. *(`--https` only)*
   - Generate a self-signed 2048-bit RSA cert valid 30 days (`CN=qwen38`), key `chmod 600`, print its SHA-256 fingerprint.
   - **Firewall (UFW)**: install if missing, `reset` (providers may ship their own rules — MassedCompute allowed port 80), default deny incoming / allow outgoing, allow 22, allow whatever port `sshd` actually listens on (found via `ss`), allow 8443, enable.
   - Why UFW + "only publish 8443": Docker-published ports bypass UFW, so only the TLS port is published and UFW closes the rest.
7. Docker: print version, `docker pull` the pinned image, `docker rm -f qwen38` (idempotent re-run), then `docker run -d`:
   - `--name qwen38 --restart on-failure:3 --gpus all`
   - `--shm-size 16g` for 1 GPU, **`--ipc=host`** for tensor parallel (workers exchange data via shared memory)
   - `-p PORT:PORT`, mounts `hf-cache → /root/.cache/huggingface` and (https) `tls → /tls:ro`
   - `--env-file vllm.env` (so vLLM reads `VLLM_API_KEY` and enforces it) and `-e HF_HUB_DISABLE_XET=1`
   - image + `MODEL_ID --host 0.0.0.0 --port PORT <vllm flags> [--ssl-keyfile /tls/key.pem --ssl-certfile /tls/cert.pem]`

The API key is inside this script, so Shadeform receives it (base64-encoded) — the script on the VM is the only place besides your `.env`.

### 4.7 Deadlines and names (lines 575–628)

- `deadline_after(hours)` — now + hours, **rounded up to the next whole minute** (names only carry minutes).
- `instance_name(deadline)` → `qwen38-until-20261026T1530Z`. **The VM's name *is* its deadline record.**
- `name_deadline(name)` — regex-parses that back to a UTC datetime; `None` if it doesn't match.
- `spend_limit(hours, price_cents)` — `ceil(hours × price × 1.10)` in dollars. The `round(…, 6)` first avoids floating-point noise (330 × 1.1 = 363.00000000000006 would round up to 364).
- `create_request(...)` builds the POST body: cloud, region, instance type, `shade_cloud: true`, name, OS image, **`auto_delete`** with `date_threshold` = deadline and `spend_threshold` = the spend limit, and `launch_configuration` of type `script` with the base64 startup script; plus `ssh_key_id` if given.

### 4.8 Talking to the VM (lines 631–686)

- `_elapsed(t0)` → `12m05s`; `_duration(sec)` → `1h20m` / `35m`.
- `vm_request(ip, port, method, path, key, body, https, timeout)` returns `(status, body, cert_DER)`. For HTTPS it deliberately disables CA verification (self-signed) but **captures the peer certificate** so identity can be checked by fingerprint instead. If nothing answers or the HTTP exchange fails, status is `None` and body is the error text — "not up yet" is a normal state, not an exception.
- `port_open(ip, port)` — raw TCP connect test.
- `fingerprint(der)` — `AA:BB:…` SHA-256 of the cert.

### 4.9 The `Start` class (lines 689–738)

Tracks progress of one `up`:

- `progress(stage, detail)` prints a line when the stage changes, or at most every 2 minutes for the same stage (avoids spam).
- `check_time()` — raises `Fail` after `START_LIMIT_SECONDS` (40 min).
- `check_cert(cert)` — remembers the first certificate seen and **fails with "SECURITY: certificate changed"** if a later one differs (basic protection against a man-in-the-middle swapping in another cert mid-start).
- `vm_state(key)` — polls `/info`: tolerates Shadeform being briefly unreachable (returns `None`); raises `Fail` if Shadeform forgot the VM, reports `status: error`, or the VM is `deleting/deleted` (auto-delete or someone else deleted it). Records `ssh_user`.
- `gpus_checked` — starts `True` for 1 GPU (no check), `False` for multi-GPU.

### 4.10 `wait_until_ready` — the readiness state machine (lines 741–810)

Four phases, any of which can raise `Fail` (which `cmd_up` turns into "delete the VM"):

1. **Wait for the VM to be `active` with an IP.** Polls `/info` every 15 s. On the first `/info`, if multi-GPU, verifies `configuration.num_gpus == requested` — a wrong-size VM is rejected immediately instead of after 40 minutes. Then prints an `ssh … tail -f start.log` hint.
2. **Wait for vLLM to answer `GET /v1/models` with the key.** 200 → proceed; 401/403 → `Fail` (our key was refused); anything else → keep waiting (image pull, ~28 GB download, model load). Every loop also re-checks the VM is still alive and the cert unchanged.
3. **Security checks:**
   - A request **without** the key must return **401**; otherwise `Fail("SECURITY: …did not refuse…")`.
   - In HTTPS mode: a *plain HTTP* request to 8443 must not get 200/401/403, and port 8000 must not accept TCP connections (proves the firewall works).
4. **Real inference test**: POST a chat completion ("Reply with one word: ready", `max_tokens 400`, 300 s timeout). Success requires HTTP 200 **and a non-empty `content`** (vLLM can answer `/v1/models` long before the model can generate; and with reasoning on, an empty `content` means it burned tokens thinking). Loops until it succeeds or the time limit hits. Returns the answer text.

### 4.11 `create_vm` (lines 813–830)

Tries up to the first 3 usable offers (cheapest first). A 200/201 with an `id` ⇒ returns `(id, offer)`. Anything else is printed as "refused" and the next offer is tried. If the network fails *during* create it raises a `Fail` warning that **a VM may exist** and to run `status` then `down`. If all attempts fail: "Nothing was created."

### 4.12 `cmd_up` — the whole flow (lines 837–944)

1. Validate `--hours`; load Shadeform key; fetch and filter offers; fail if none usable (nothing created).
2. Load/generate the vLLM key.
3. Compute deadline, name; pick `usable[0]`; **print the Plan** (offer, GPUs, deadline, cost cap, mode). Plain HTTP gets a prominent "NOT encrypted — non-sensitive only" warning.
4. **Confirmation**: unless `--yes`, requires a TTY and typing `y`/`yes`. Non-interactive without `--yes` fails rather than spending money silently.
5. Build the startup script. Install handlers so SIGTERM/SIGHUP behave like Ctrl-C (raise `KeyboardInterrupt`).
6. Create the VM with **interrupts ignored** (a create cut short could leave an invisible VM), then restore handlers.
7. `wait_until_ready` inside `try/except BaseException`. On *any* failure or interrupt: print the failure and last stage, **delete the VM and confirm**, hint to watch SSH next time, return 1 (or 130 on interrupt).
8. On success print: ready time, VM details, deadline, GPU info, and the **LiteLLM gateway settings** (API base, key = "the value in .env", provider `hosted_vllm`, model, 900 s timeout). In HTTPS mode also: `ssl_verify false` explanation and the certificate SHA-256 to compare over SSH. Finally the exact `down <id>` command.

### 4.13 `status`, `down`, `reap` (lines 947–1030)

- **`status`** — lists tool instances: id/name, cloud/region/ip/status, price per hour, Shadeform's cost estimate, uptime (from `created_at`), and time left (from the name; `OVERDUE … (run reap)` if past).
- **`down [id]`** —
  - With an id: fetch its info; refuse if unknown or **if the name lacks the prefix** ("this tool did not create it").
  - Without id: take the tool's non-deleting instances; none → nothing to do; **more than one → refuses and lists them** (never guesses which to delete).
  - Deletes each via `delete_and_confirm`; exit 1 if any isn't confirmed.
- **`reap`** — for live tool instances: deletes those whose name-deadline ≤ now; **warns about and does not touch** names with unreadable deadlines; prints a summary. Nothing runs it automatically — you must schedule it (cron) if you want the third safety net.

### 4.14 CLI and `main` (lines 1035–1100)

`build_parser` defines the subcommands and flags; each subparser stores its function with `set_defaults(func=…)`. `main` runs it and maps exceptions: `Fail` → `ERROR: …`/1; network errors → "cannot reach Shadeform"/1; `KeyboardInterrupt` → `Interrupted.`/130.

---

## 5. The safety layers, in one place

| Risk | Defence |
|---|---|
| Forgetting a VM | Mandatory `--hours`; Shadeform `date_threshold`; `spend_threshold` (×1.10); `reap` via name-encoded deadline; `status` shows time left. |
| Deleting someone else's VM | Everything filters on `NAME_PREFIX`; `down <id>` re-checks the name. |
| Deleting the wrong one of several | `down` with several running refuses and lists. |
| Failed/aborted start keeps billing | `cmd_up` always deletes on failure/interrupt; 40-min limit; early wrong-GPU-count and error-status detection. |
| Deletion interrupted | `delete_and_confirm` ignores signals, retries, waits for Shadeform to confirm. |
| Accidental spend | Confirmation prompt (or `--yes`); refuses to run non-interactively without `--yes`. |
| Wasting money on an incompatible host | CUDA ≥ 13 screening in `split_offers`, plus a driver-version gate in the startup script. |
| Unauthenticated access | vLLM requires `VLLM_API_KEY`; `up` verifies a key-less request gets 401. |
| Eavesdropping | `--https`; plain HTTP warns loudly. |
| Firewall gaps (HTTPS) | UFW reset + deny incoming; verifies plain HTTP refused on 8443 and 8000 closed. |
| TLS impersonation mid-start | Certificate must stay identical; fingerprint printed for manual comparison. |
| Secret leakage in output | All output via `say()` → `redact()`; `.env` is chmod 600 when created; key file on VM is mode 600. |

---

## 6. Things worth knowing (limits and quirks)

- **Plain HTTP mode has no firewall at all** and sends the key and prompts in clear text. Only for non-sensitive tests.
- **HTTPS is self-signed.** Nothing validates the certificate automatically for your gateway — you set `ssl_verify false` and, if you care, compare the printed fingerprint over SSH yourself. The script itself pins the cert only within one `up` run.
- **`reap` is not automatic.** Shadeform's own auto-delete is the primary enforcement; `reap` only helps if you run it.
- **Tiny leak window:** between `create_vm` returning (interrupts restored) and entering the `try` around `wait_until_ready`, there's a line of `say()` where a Ctrl-C would escape without deleting. The VM would then be caught by Shadeform's auto-delete or `reap`, not instantly.
- **Cost figures are estimates**: the "cost cap" is Shadeform's spend threshold; "cost so far" is Shadeform's own estimate.
- **Cold start every time**: ~8.7 GB image pull + ~28 GB model download on each new VM, hence the 40-minute limit and typical readiness in the tens of minutes.
- **Deadline precision** is one minute (name format `YYYYMMDDTHHMMZ`).
- **Price units**: Shadeform returns `hourly_price` in cents; the script divides by 100 when printing.
- **The vLLM key passes through Shadeform** (it's in the base64 startup script you send them).
- **Only on-demand** offers are considered; spot is ignored.
- **Standalone**: no dependency on `deploy.py` or the `modal` package, and vice versa; the serving constants were copied once and now evolve independently.

---

## 7. "Where do I change X?"

| I want to… | Edit |
|---|---|
| Change a vLLM flag / the model | Constants at lines 53–81 and `vllm_flags()` (84). |
| Require a different GPU size or CUDA | `MIN_GPU_MEMORY_GB`, `MIN_HOST_CUDA`, and the `580` driver check in `startup_script`. |
| Change idle/boot/delete timing | `START_LIMIT_SECONDS`, `POLL_SECONDS`, `DELETE_CONFIRM_SECONDS` (or their env vars). |
| Allow longer rentals | `MAX_HOURS`. |
| Change the cost safety margin | `SPEND_MARGIN`. |
| Change what the VM runs / opens | `startup_script()`. |
| Change what counts as "ready" | `wait_until_ready()`. |
| Change which offer is picked | `split_offers()` ordering (`order`, line 390); `cmd_up` uses `usable[0]`. |
| Rename the tool's VMs | `NAME_PREFIX` — **careful**: VMs created under the old prefix become invisible to `status/down/reap`. |
| Add a CLI flag | `build_parser()` and the relevant `cmd_*`. |

---

## 8. Typical session

```bash
python3 shadeform_deploy.py offers                         # look, free
python3 shadeform_deploy.py up --hours 1 --https           # confirm with y; wait for READY
#   → use the printed API Base / model / certificate fingerprint in the gateway
python3 shadeform_deploy.py status                         # check cost and time left
python3 shadeform_deploy.py down                           # done: delete, billing stops
python3 shadeform_deploy.py reap                           # (cron) safety sweep
```

Multi-GPU: add `--tensor-parallel 2` to both `offers` and `up`.
