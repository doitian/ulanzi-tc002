import threading

from ulanzi_tc002.frames import blank_frame, publish, scroll_frames, text_frame
from ulanzi_tc002.server.apps.base import App, AppDisabled


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
            from ulanzi_tc002.ansi_text import ansi_frames
            return iter(ansi_frames(self.glyphs))
        text, color = self.state
        return iter(self.frames(text, color)) if text else iter([blank_frame()])

    def update(self, payload):
        from ulanzi_tc002.colors import resolve_color
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
            from ulanzi_tc002.ansi_text import parse_ansi
            glyphs = parse_ansi(text, color)
        elif text:
            text_frame(text, color)
        with self.condition:
            self.ansi, self.glyphs = ansi, glyphs
            self.visible_length = len(glyphs) if ansi else len(text)
            from ulanzi_tc002.ansi_text import text_width
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


class TextApp(App):
    name = "text"
    title = "Text"

    def __init__(self, device, tick):
        super().__init__()
        self.device = device
        self.tick = tick
        self.widget = TextWidget(device, self.name, tick, publish, scroll_frames)

    def start(self):
        self.widget = TextWidget(self.device, self.name, self.tick, publish, scroll_frames)
        self.widget.worker.start()
        self.enabled = True

    def stop(self):
        try:
            self.device.post(publish, self.name, blank_frame())
        except (OSError, ValueError, ConnectionError) as error:
            print(f"Display clear failed: {error}", flush=True)
        self.widget.close()
        self.enabled = False

    def update(self, payload):
        if not self.enabled:
            raise AppDisabled("App is disabled")
        return self.widget.update(payload)

    def snapshot(self):
        state = self.widget.state
        return {
            "name": self.name,
            "title": self.title,
            "enabled": self.enabled,
            "text": state[0] if state else None,
            "color": state[1] if state else None,
            "ansi": self.widget.ansi,
            "error": self.widget.error,
            "app": self.name,
        }
