# Tasks

## 1. A standalone tool with the measured settings (free)

> `shadeform_deploy.py` imports nothing from `deploy.py` and needs no `modal` package (operator requirement). `deploy.py` must not change. Every task below ends by checking `git diff --quiet HEAD -- deploy.py`.

- [x] 1.1 Create `shadeform_deploy.py` with its settings section only. It holds constants for the model, context, KV cache, GPU memory share, reasoning parser, chat-template default, tool parser with auto tool choice, MTP and the pinned image (values in design.md), and a function that returns the vLLM flag list. It uses the standard library only. Verify:
  - `python3 shadeform_deploy.py --help` runs with the **system** Python, outside the project venv;
  - the file contains no `import deploy` and no `modal`;
  - `deploy.py` is unchanged.
- [x] 1.2 One-time check at delivery. Compare the tool's flag list with the vLLM flags in `serve()` of `deploy.py` at commit `68cff7e`, read with `git show 68cff7e:deploy.py`, flags after the model name, ignoring host and port. Record the result here. Verify they are identical, flag for flag and in order. This is a check, not a permanent test.
  - **Result (2026-10-01): identical.** `serve()` at `68cff7e` was read with `git show` and evaluated from its own constants, without importing `modal`:
    - same model, `Qwen/Qwen3.8-27B-FP8`;
    - after dropping `--host 0.0.0.0 --port 8000`, the same 15 arguments in the same order: `--max-model-len 250000 --kv-cache-dtype fp8 --gpu-memory-utilization 0.9 --reasoning-parser qwen3 --default-chat-template-kwargs {"reasoning_effort": "low"} --enable-auto-tool-choice --tool-call-parser qwen3_xml --speculative-config {"method": "mtp", "num_speculative_tokens": 3}`.

## 2. Choosing an offer (free: the public API needs no key)

- [x] 2.1 In `shadeform_deploy.py`, implement `offers`. It reads `GET /instances/types` and keeps offers with one GPU, 80 GB or more of GPU memory, available now, and an `os` option of `cuda13` or newer. It orders them by hourly price and supports `--region` / `--cloud` filters. Offers that fail only the CUDA rule are listed under "not usable", with the reason. Verify against the live API: today's MassedCompute A100 (`cuda13.0`) is usable, and Denvr and Crusoe (`cuda12.x`) appear as not usable.
- [x] 2.2 Add `tests/test_shadeform_offers.py`, using a saved sample of the `/instances/types` response. Verify the filtering, ordering, region/cloud filters and not-usable reasons, with no network.
- [x] 2.3 *(Added during apply, at the operator's request.)* Add a `--gpu` filter to `offers` and `up`, e.g. `--gpu H100`, which matches any part of the GPU or instance type, so a stronger GPU can be chosen over the cheapest one. Verify:
  - the offers test covers the filter;
  - the lifecycle test shows `up --gpu H100` creating the cheapest H100 rather than a cheaper A100, and `--gpu B200` creating nothing;
  - live, `offers --gpu H100` lists only H100s.

## 3. Up, status, down, reap (free: tested against a fake API)

- [x] 3.1 Build the create request for stage A: a startup-script launch (design.md) whose bash script pulls and runs `vllm/vllm-openai:v0.30.0` with `--gpus all --shm-size 16g -p 8000:8000`, the Hugging Face cache mount, `-e VLLM_API_KEY -e HF_HUB_DISABLE_XET=1`, and `MODEL_ID --port 8000` plus the tool's flag list from 1.1, each argument shell-quoted. The instance name is `qwen38-until-<UTC deadline>`. The request also carries the offer's `os`, and `auto_delete` with `date_threshold` = the deadline and `spend_threshold` = hours × hourly price + 10% (design.md). Verify:
  - a test decodes the payload, checks the name, `os`, `auto_delete` and launch type, and runs `bash -n` on the script;
  - a test **runs the script locally with fake `docker`/`nvidia-smi`** and asserts the exact argument list the container receives, JSON values intact.
- [x] 3.2 Implement `up --hours N` (required, fractions allowed, no default). It creates the VM (on a capacity error, tries the next usable offer, up to 3), polls `/info` until `active` with an IP, then polls `/v1/models` with the key every 15 s. It sends one short chat completion, and prints the endpoint and gateway settings only after a real answer. It prints a loud warning in plain-HTTP mode. On the 40-minute limit, `status: error` or Ctrl-C, it deletes the VM and waits until Shadeform reports it deleted. Verify against a local fake Shadeform API plus a fake vLLM, covering five cases: the normal path, a capacity error followed by success, a never-ready VM that gets deleted, Ctrl-C that gets deleted, and a VM that reports an error.
- [x] 3.3 Implement `down [id]`: delete the VM, and report success only once `/info` shows it deleted. With no id, it deletes the tool's only running instance, and refuses if there are several. Verify against the fake API.
- [x] 3.4 Implement `status`: for the tool's instances (names starting `qwen38-until-`), list id, provider, region, IP, hourly price, `cost_estimate` and time left. Verify against the fake API, including an instance past its deadline, which is shown as overdue.
- [x] 3.5 Implement `reap`: delete every tool instance past its deadline, confirm each deletion, and ignore every other instance. Verify against a fake API holding an expired tool instance, a current one and a non-tool instance: only the first is deleted.
- [x] 3.6 Handle the secrets. Read `SHADEFORM_API_KEY` and `VLLM_API_KEY` from `.env`; if `VLLM_API_KEY` is missing, generate one, append it to `.env`, and say so without printing it. Verify by running every command against the fake API with dummy keys, and checking that neither key appears in any output or file the tool writes.

## 4. Stage B: HTTPS and firewall (free to build)

- [x] 4.1 Add `up --https`. The same startup script also creates a self-signed certificate with `openssl`, sets UFW to deny incoming except 22 and 8443, publishes only 8443, mounts the certificate read-only, and adds `--port 8443 --ssl-keyfile --ssl-certfile`. Verify the script passes `bash -n`, and a test runs it with fake `docker`/`ufw`/`openssl`/`nvidia-smi` and asserts the firewall commands, the published port and the vLLM arguments.
- [x] 4.2 In HTTPS mode, the readiness checks and the printed gateway settings use `https://<ip>:8443/v1`. The tool prints the certificate fingerprint it sees on the first connection, and states that the gateway must accept the self-signed certificate (`ssl_verify: false` for this model). Verify against the fake vLLM served over a local self-signed certificate.

## 5. Operator documentation (free)

- [x] 5.1 Add a "Shadeform" section to `README.md` covering:
  - what's needed first: an account, a few dollars of credit, and `SHADEFORM_API_KEY` in `.env`;
  - each command with a real example;
  - the gateway settings for stage A and stage B (API Base, key, `ssl_verify`, a 900 s timeout);
  - a cron line for `reap` every 15 minutes;
  - what a start costs and how long it takes;
  - how to read a failed start over SSH (`journalctl -u init-script`, `docker logs`).

  Verify every command in it runs as written against the fake API.
- [x] 5.2 Add a short Part 12 to `GUIDE.md`, "Moving off Modal: running it on rented VMs". It covers what Modal did for us that we now do ourselves (HTTPS, scale-to-zero, a stable URL, the container's CUDA), and the one-command-up, one-command-down discipline. Verify its commands match the README.

## 6. Paid verification (Shadeform credit, gated)

> Before this group: the operator reports their Shadeform balance, which is recorded in `NOTES.md`. The ceiling for this phase is $5 of Shadeform credit. The Modal budget is not used.

- [x] 6.1 Record the Shadeform balance, and verify `offers` shows at least one usable offer at that moment. If none is usable, stop and retry later; nothing is created.
- [x] 6.2 Stage A: run `up --hours 1` on the cheapest usable offer. Record how long each stage took (provisioning, container, model download, vLLM start) and the hourly price. Verify that a real completion returns, and that a request without the key is refused.
  - **Result (2026-10-01): READY in 14m58s.** MassedCompute `A100_sxm4_80G_DGX`, beltsville-usa-1, $1.38/hr.
    - **Provisioning:** 2m50s to `active`.
    - **Startup script → image pulled:** 2m06s.
    - **Model download:** ~4.5 min for 28 GB.
    - **vLLM start:** ~4 min (weights load, 47 s compile, KV cache, warmup).
    - **Checks:** the model answered; a request without the key was refused with 401 (from the tool and from `curl`).
    - **On the VM:** driver 580.126.09, KV cache 38.33 GiB = 1,072,674 tokens.
- [x] 6.3 Point the gateway model at the printed API Base and key. Verify one chat request and one tool call through the gateway, from `curl`. Then run `eval/run_eval.py code-sql-top-customers` with `EVAL_URL` set to the VM, and verify its automated check passes, as it did on Modal.
  - **Partly done (2026-10-01).** Direct to the VM:
    - `code-sql-top-customers@shadeform` **PASS** (`eval/results/2026-10-01/`);
    - a tool call returned `get_weather({"city": "Cairo"})` in 3.8 s;
    - decode 77.5 tok/s, against 73.2 on Modal with the same FP8 KV cache.

    **The gateway part was not done on that VM:** the gateway entry wasn't pointed at the VM before the idle-VM fallback `down` at 11:02.
  - **Gateway part done by the operator,** on VMs they started (A100, 11:09–11:30 and 11:43–12:38 UTC). They pointed `Qwen3.8-27B-FP8-shadeform` on `dev.gateway.areeb.me` at `http://154.54.100.38:8000/v1`. The gateway connection test failed while the model was still starting, then worked once it was ready.
    - Reported on 2026-10-01: "I validate everything and it work perfectly".
    - Source: the operator's own checks through the gateway and clients. These requests were not observed from here: that VM had no SSH key, so its logs couldn't be read.
- [x] 6.4 Verify `/info` for the VM shows the `auto_delete` deadline sent at create. Run `reap` while the VM is within its deadline, and verify it deletes nothing. Then run `down`, and verify `status` shows no instances and Shadeform lists the VM as deleted.
  - **Result (2026-10-01):**
    - `/info` held `auto_delete {date_threshold: 2026-10-01T11:31:00Z, spend_threshold: 1.52}`, plus the CUDA 13 `os`, our SSH key and the script launch.
    - `reap` at 10:48: 0 deleted, 1 within deadline.
    - `down` at 11:02:34: `deleting` was confirmed at once; 12 s later `status` showed no instances.
    - `/info` then reported `status: deleted` with a final `cost_estimate` of $0.677. (It answers 200 with `deleted`, not 404; the tool handles both.)
- [x] 6.5 Stage B: run `up --https --hours 1`. Verify HTTPS answers, plain HTTP to the same port fails, and port 8000 is closed. Then connect the gateway with `ssl_verify: false`, send one request through it, and run `down`.
  - **Result (2026-10-01): verified.** VM `8b7c4ca0`, A100, created 12:46 UTC, READY in 15m05s.
    - **The tool's checks, re-run with `curl`:** HTTPS without the key gave 401; plain HTTP to 8443 was refused; port 8000 was closed. The certificate fingerprint matched the one logged on the VM.
    - **Found:** MassedCompute's image already allowed port 80 in UFW. It was removed on the VM, and the script now runs `ufw --force reset` first.
    - **Found:** the gateway first rejected the certificate (a TCP capture showed it hanging up after the TLS hello; 0 requests reached vLLM), because LiteLLM's `openai` provider ignores a per-model `ssl_verify`. A new entry `Qwen3.8-27B-Shadeform-vllm` with provider **vLLM (`hosted_vllm`)** and `ssl_verify: false` worked: `35.211.252.138 POST /v1/chat/completions 200` in vLLM's log at ~13:24 UTC.
- [x] 6.6 Record the spend from the Shadeform dashboard against the $5 ceiling, and verify no instance is still running.
  - **Result:** the dashboard showed **$39.42** on 2026-10-04 (operator's screenshot, before phase 5 spent anything). That's $42.62 − $39.42 = **$3.20** for phase 4, against the $3.19 summed from Shadeform's `cost_estimate`. The estimates are accurate. Phase 4 is under its $5 ceiling, with no instance left running (`status` empty on 2026-10-01).

## 7. Close-out

- [x] 7.1 Add a `NOTES.md` entry: the measured start-time breakdown, the cost per start and per hour against Modal, any provider-specific surprise, and the stage A and B results. Verify every number comes from group 6.
- [ ] 7.2 Verify `git diff --quiet HEAD -- deploy.py` succeeds: the Modal deployment's file is byte-for-byte unchanged by this phase.
  - **Not met as written (2026-10-01).** This change's files never touched `deploy.py` (the check passed at every step until 12:11 local). Then the **operator edited it deliberately, and chose to keep the edit**:
    - `IDLE_WINDOW_SECONDS` went from 5 to 10 minutes;
    - two comments are scrambled;
    - it is **not deployed** (the live Modal app predates the edit).

    It is left open for the operator: restore with `git checkout -- deploy.py`, or accept the edit and archive with this task open.
- [x] 7.3 Scan all new and changed files for `SHADEFORM_API_KEY`, `VLLM_API_KEY` and the Modal token, and verify there are no matches before the operator is asked to approve a commit.
  - **Result (2026-10-01):** 23 new or changed files scanned for the Modal token, `SHADEFORM_API_KEY` and `VLLM_API_KEY`: **0 matches**; `.env` is git-ignored. Re-run it right before any commit if files change.
