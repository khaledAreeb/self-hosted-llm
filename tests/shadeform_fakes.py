"""A fake Shadeform API and a fake vLLM, on 127.0.0.1, for the
shadeform_deploy.py tests. Nothing here touches the network or costs money."""

import datetime
import http.server
import json
import ssl
import threading
import uuid

MODEL = "Qwen/Qwen3.8-27B-FP8"


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _quiet_server(handler):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    server.handle_error = lambda *a: None          # e.g. plain HTTP sent to the TLS port
    return server


class FakeShadeform:
    """Shadeform's instance API, as the docs describe it.

    boot: the statuses a new instance walks through, one step per /info call.
    capacity_failures: how many creates to refuse first, as when an offer's
    capacity vanishes between listing and creating."""

    def __init__(self, key, types, boot=("creating", "pending_provider", "pending", "active"),
                 capacity_failures=0, report_gpus=None):
        """report_gpus: the GPU count /info reports, to fake a wrong machine;
        by default the count of the instance type that was ordered."""
        self.key, self.types, self.boot = key, types, list(boot)
        self.report_gpus = report_gpus
        self.capacity_failures = capacity_failures
        self.instances = {}
        self.calls = []                 # (method, path, parsed body)
        self.lock = threading.Lock()
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n)) if n else None

            def do_GET(self):
                with fake.lock:
                    fake.calls.append(("GET", self.path, None))
                    if self.path == "/instances/types":           # public
                        return self._send(200, {"instance_types": fake.types})
                    if self.headers.get("X-API-KEY") != fake.key:
                        return self._send(401, {"error": "unauthorized"})
                    if self.path == "/instances":
                        return self._send(200, {"instances": [
                            dict(i) for i in fake.instances.values() if i["status"] != "deleted"]})
                    parts = self.path.strip("/").split("/")
                    if len(parts) == 3 and parts[0] == "instances" and parts[2] == "info":
                        i = fake.instances.get(parts[1])
                        if not i or i["status"] == "deleted":
                            return self._send(404, {"error": "not found"})
                        fake._advance(i)
                        return self._send(200, dict(i))
                    return self._send(404, {"error": "no route"})

            def do_POST(self):
                body = self._body()
                with fake.lock:
                    fake.calls.append(("POST", self.path, body))
                    if self.headers.get("X-API-KEY") != fake.key:
                        return self._send(401, {"error": "unauthorized"})
                    if self.path == "/instances/create":
                        if fake.capacity_failures > 0:
                            fake.capacity_failures -= 1
                            return self._send(400, {"error": "instance type is out of capacity"})
                        iid = fake.add(body["name"], status=fake.boot[0], cloud=body["cloud"],
                                       region=body["region"], request=body,
                                       num_gpus=fake.report_gpus or fake._gpus_of(body))
                        return self._send(200, {"id": iid})
                    parts = self.path.strip("/").split("/")
                    if len(parts) == 3 and parts[0] == "instances" and parts[2] == "delete":
                        i = fake.instances.get(parts[1])
                        if not i or i["status"] == "deleted":
                            return self._send(404, {"error": "not found"})
                        i["status"] = "deleting"
                        return self._send(200, {})
                    return self._send(404, {"error": "no route"})

        self.server = _quiet_server(Handler)

    def _advance(self, i):
        """One /info call moves a booting instance one status further."""
        if i["status"] in self.boot:
            step = self.boot.index(i["status"])
            if step + 1 < len(self.boot):
                i["status"] = self.boot[step + 1]
        if i["status"] == "active":
            i["ip"] = "127.0.0.1"
            i["info_calls_active"] = i.get("info_calls_active", 0) + 1

    def _gpus_of(self, body):
        for t in self.types:
            if (t.get("cloud"), t.get("shade_instance_type")) == (body["cloud"], body["shade_instance_type"]):
                return (t.get("configuration") or {}).get("num_gpus")
        return 1

    def add(self, name, status="active", cloud="massedcompute", region="desmoines-usa-1",
            created_minutes_ago=0, request=None, num_gpus=1):
        iid = str(uuid.uuid4())
        created = _now() - datetime.timedelta(minutes=created_minutes_ago)
        self.instances[iid] = {
            "id": iid, "name": name, "cloud": cloud, "region": region,
            "shade_instance_type": "A100_sxm4_80G", "status": status,
            "ip": "127.0.0.1" if status == "active" else None, "ssh_user": "shadeform",
            "hourly_price": 138, "cost_estimate": "0.42",
            "created_at": created.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
            "launch_configuration": (request or {}).get("launch_configuration"),
            "auto_delete": (request or {}).get("auto_delete"),
            "configuration": {"num_gpus": num_gpus},
        }
        return iid

    def creates(self):
        return [b for m, p, b in self.calls if m == "POST" and p == "/instances/create"]

    def deletes(self):
        return [p.split("/")[2] for m, p, b in self.calls if m == "POST" and p.endswith("/delete")]

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return "http://127.0.0.1:%d" % self.server.server_port

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class FakeVLLM:
    """vLLM's OpenAI API with --api-key: /v1/models and /v1/chat/completions.

    key: the key it requires, or a function returning it (for a key the tool
    generates during the test). open_without_key: a broken server that
    answers anyone. tls: (certfile, keyfile) to serve HTTPS."""

    def __init__(self, key, open_without_key=False, tls=None, answer="ready"):
        self.key = key if callable(key) else (lambda: key)
        self.open_without_key, self.answer = open_without_key, answer
        self.requests = []              # (method, path, had the right key)
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _authorized(self):
                ok = self.headers.get("Authorization") == "Bearer " + fake.key()
                fake.requests.append((self.command, self.path, ok))
                return ok or fake.open_without_key

            def do_GET(self):
                if not self._authorized():
                    return self._send(401, {"error": "Unauthorized"})
                if self.path == "/v1/models":
                    return self._send(200, {"object": "list", "data": [{"id": MODEL}]})
                return self._send(404, {"error": "no route"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if n else {}
                if not self._authorized():
                    return self._send(401, {"error": "Unauthorized"})
                if self.path == "/v1/chat/completions" and body.get("model") == MODEL:
                    return self._send(200, {"choices": [{"index": 0, "finish_reason": "stop",
                                                         "message": {"role": "assistant",
                                                                     "content": fake.answer}}]})
                return self._send(404, {"error": "no route"})

        self.server = _quiet_server(Handler)
        if tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(*tls)
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.server.server_port

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def closed_port():
    """A local port with nothing listening on it."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
