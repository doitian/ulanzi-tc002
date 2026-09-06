import base64

from ulanzi_tc002.canvas import fit_to_canvas
from ulanzi_tc002.frames import blank_frame, image_data_uri, image_frame, parse_image, publish
from ulanzi_tc002.server.apps.base import App


class ImageWidget:
    def __init__(self, device, app):
        self.device, self.app = device, app
        self.state = None
        self.error = None

    def update(self, payload):
        if not isinstance(payload, dict) or "image" not in payload:
            raise ValueError("Provide a JSON object with an 'image'")
        image = payload["image"]
        duration = payload.get("duration", 10)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
            raise ValueError("Duration must be positive")
        if not isinstance(image, str):
            raise ValueError("Image must be a data URI or base64 string")
        if image == "":
            frame = blank_frame()
            data_uri = ""
        else:
            data_uri = parse_image(image)
            payload = data_uri.split(",", 1)[1]
            data_uri = image_data_uri(fit_to_canvas(base64.b64decode(payload)))
            frame = image_frame(data_uri, duration)
        self.state = (data_uri, duration)
        try:
            self.device.post(publish, self.app, frame)
            self.error = None
        except (OSError, ValueError) as error:
            self.error = str(error)
            raise ConnectionError(str(error)) from error
        return {"image": data_uri, "duration": duration, "app": self.app, "accepted": True}

    def close(self):
        pass


class ImageApp(App):
    type = "image"
    title = "Image"

    def __init__(self, device, name):
        super().__init__(name)
        self.device = device
        self.widget = ImageWidget(device, name)

    def restore(self, item):
        image = item.get("image")
        if not isinstance(image, str):
            return
        duration = item.get("duration", 10)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
            duration = 10
        self._pending = {"image": image, "duration": duration}

    def start(self, create=False):
        if self._started:
            return
        self._started = True
        payload = self._pending
        self._pending = None
        if payload is not None:
            try:
                self.widget.update(payload)
            except (OSError, ValueError, ConnectionError) as error:
                print(f"Display restore failed: {error}", flush=True)

    def stop(self):
        self.widget.close()

    def update(self, payload):
        return self.widget.update(payload)

    def config(self):
        data = {"type": self.type}
        state = self.widget.state
        if state is not None:
            data["image"] = state[0]
            data["duration"] = state[1]
        return data

    def snapshot(self):
        state = self.widget.state
        return {
            "name": self.name,
            "type": self.type,
            "title": self.title,
            "image": state[0] if state else None,
            "duration": state[1] if state else None,
            "error": self.widget.error,
            "app": self.name,
        }
