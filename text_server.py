"""HTTP-controlled text widget with a serialized display worker."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading


def blank_frame():
    # {} deletes the custom app. Explicit black pixels clear it without deletion.
    return {"duration": 10, "text": [], "image": [],
            "draw": [{"df": [0, 0, 52, 16, "#000000"]}]}


class TextWidget:
    def __init__(self, device, app, tick, publish, frames):
        self.device, self.app, self.tick = device, app, tick
        self.publish, self.frames = publish, frames
        self.condition = threading.Condition()
        self.state = None
        self.revision = 0
        self.stopped = False
        self.error = None
        self.ansi = False
        self.glyphs = []
        self.visible_length = 0
        self.rendered_width = 0
        self.worker = threading.Thread(target=self.run, daemon=True)

    def cycle(self):
        if self.ansi:
            from ansi_text import ansi_frames
            return iter(ansi_frames(self.glyphs))
        text, color = self.state
        return iter(self.frames(text, color)) if text else iter([blank_frame()])

    def update(self, payload):
        from tc002 import resolve_color, text_frame
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            raise ValueError("Provide a JSON object with a string 'text'")
        text = payload["text"]
        ansi = payload.get("ansi", False)
        if not isinstance(ansi, bool):
            raise ValueError("'ansi' must be a boolean")
        color = payload.get("color", "white")
        if not isinstance(color, str):
            raise ValueError("Color must be a name or #RRGGBB string")
        color = resolve_color(color)
        if not ansi and len(text) > 256:
            raise ValueError("Text cannot exceed 256 characters")
        glyphs = []
        if ansi:
            from ansi_text import parse_ansi
            glyphs = parse_ansi(text, color)
        elif text:
            text_frame(text, color)
        with self.condition:
            self.ansi, self.glyphs = ansi, glyphs
            self.visible_length = len(glyphs) if ansi else len(text)
            from ansi_text import text_width
            self.rendered_width = text_width(glyphs) if ansi else len(text) * 6
            self.state = (text, color)
            self.revision += 1
            self.iterator = self.cycle()
            try:
                self.device.post(self.publish, self.app, next(self.iterator))
                self.error = None
            except (OSError, ValueError) as error:
                self.error = str(error)
                raise ConnectionError(str(error)) from error
            finally:
                self.condition.notify_all()
            return {"text": text, "color": color, "ansi": ansi, "app": self.app, "accepted": True}

    def run(self):
        with self.condition:
            while not self.stopped:
                if self.state is None:
                    self.condition.wait()
                    continue
                revision = self.revision
                interval = self.tick if self.rendered_width > 52 else 5
                if self.condition.wait_for(
                    lambda: self.stopped or self.revision != revision, timeout=interval
                ):
                    continue
                frame = next(self.iterator, None)
                if frame is None:
                    self.iterator = self.cycle()
                    frame = next(self.iterator)
                try:
                    self.device.post(self.publish, self.app, frame)
                    self.error = None
                except (OSError, ValueError) as error:
                    self.error = str(error)
                    print(f"Display update failed: {error}", flush=True)

    def close(self):
        with self.condition:
            self.stopped = True
            self.condition.notify_all()
        if self.worker.is_alive():
            self.worker.join()


def make_server(widget, host, port):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def respond(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/text":
                self.respond(404, {"error": "Use POST /text"})
                return
            if self.headers.get_content_type() != "application/json":
                self.respond(415, {"error": "Content-Type must be application/json"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32768:
                    self.respond(413, {"error": "JSON body must be 1..32768 bytes"})
                    return
                payload = json.loads(self.rfile.read(length))
                result = widget.update(payload)
            except (ValueError, UnicodeError) as error:
                self.respond(400, {"error": str(error)})
                return
            except OSError as error:
                self.respond(502, {"error": str(error), "accepted": False})
                return
            self.respond(200, result)

        def do_GET(self):
            if self.path != "/text":
                self.respond(404, {"error": "Use GET /text"})
                return
            with widget.condition:
                state = widget.state
                self.respond(200, {"text": state[0] if state else None,
                                   "color": state[1] if state else None,
                                   "ansi": widget.ansi,
                                   "app": widget.app, "error": widget.error})

    return ThreadingHTTPServer((host, port), Handler)


def serve(device, app, host, port, tick, publish, frames):
    widget = TextWidget(device, app, tick, publish, frames)
    server = make_server(widget, host, port)
    widget.worker.start()
    print(f"Text API listening at http://{host}:{port}/text; "
          f"select '{app}' in the clock's DIY/custom apps. Ctrl+C stops the server.", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        widget.close()
