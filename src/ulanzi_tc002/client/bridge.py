from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

from ulanzi_tc002.client.opencode import summarize

STALE_SECONDS = 5
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8009


class BridgeStore:
    def __init__(self, stale=STALE_SECONDS):
        self.stale = stale
        self.lock = threading.Lock()
        self.instances = {}

    def update(self, provider, payload):
        if not isinstance(payload, dict):
            raise ValueError("Provide a JSON object")
        instance = payload.get("id")
        if not isinstance(instance, str) or not instance:
            raise ValueError("Provide a string id")
        raw_status = payload.get("status", {})
        if not isinstance(raw_status, dict):
            raise ValueError("status must be an object")
        status = {}
        for sid, kind in raw_status.items():
            if not isinstance(sid, str) or kind not in ("idle", "busy", "retry"):
                raise ValueError("status values must be idle, busy, or retry")
            status[sid] = kind
        raw_blocking = payload.get("blocking", [])
        if not isinstance(raw_blocking, list) or any(not isinstance(sid, str) for sid in raw_blocking):
            raise ValueError("blocking must be an array of strings")
        with self.lock:
            self.instances[(provider, instance)] = {
                "status": status,
                "blocking": list(raw_blocking),
                "updated": time.time(),
            }

    def snapshot(self, provider, now=None):
        now = time.time() if now is None else now
        status_by_id = {}
        blocking = set()
        with self.lock:
            stale = [
                key for key, item in self.instances.items()
                if key[0] == provider and now - item["updated"] > self.stale
            ]
            for key in stale:
                del self.instances[key]
            for (name, instance), item in self.instances.items():
                if name != provider:
                    continue
                for sid, kind in item["status"].items():
                    status_by_id[f"{instance}:{sid}"] = kind
                for sid in item["blocking"]:
                    blocking.add(f"{instance}:{sid}")
        return summarize(status_by_id, blocking)


def make_handler(store, providers):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"ok": True})
                return
            self.send_error(404)

        def do_POST(self):
            parts = self.path.strip("/").split("/")
            if len(parts) != 2 or parts[0] != "providers" or parts[1] not in providers:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400)
                return
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
                store.update(parts[1], payload)
            except (ValueError, UnicodeDecodeError):
                self.send_error(400)
                return
            self.send_response(204)
            self.end_headers()

        def _send(self, code, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    return Handler


class Bridge:
    def __init__(self, host, port, store, providers):
        self.httpd = ThreadingHTTPServer((host, port), make_handler(store, frozenset(providers)))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self):
        host, port = self.httpd.server_address[:2]
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        if ":" in str(host) and not str(host).startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{port}"

    def start(self):
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
