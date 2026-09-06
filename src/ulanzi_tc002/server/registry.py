import json
import re
import threading

from ulanzi_tc002.frames import unpublish
from ulanzi_tc002.server.apps.image import ImageApp
from ulanzi_tc002.server.apps.text import TextApp

KINDS = frozenset({"text", "image"})
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


class AppExists(ValueError):
    pass


class Registry:
    def __init__(self, settings, device):
        self.settings = settings
        self.device = device
        self.lock = threading.Lock()
        self.apps = {}
        self._load()

    def _config_path(self):
        return self.settings.data_dir / "config.json"

    def _make(self, name, kind):
        if kind == "text":
            return TextApp(self.device, self.settings.tick, name)
        if kind == "image":
            return ImageApp(self.device, name)
        raise ValueError("Type must be text or image")

    def _load(self):
        path = self._config_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        apps = data.get("apps")
        if not isinstance(apps, dict):
            return
        for name, item in apps.items():
            if not isinstance(item, dict) or not NAME_RE.fullmatch(name):
                continue
            kind = item.get("type")
            if kind not in KINDS:
                if name in KINDS and item.get("enabled", True):
                    kind = name
                else:
                    continue
            if item.get("enabled") is False:
                continue
            app = self._make(name, kind)
            app.restore(item)
            self.apps[name] = app

    def _save(self):
        path = self._config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"apps": {name: app.config() for name, app in self.apps.items()}}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def start(self):
        with self.lock:
            for app in self.apps.values():
                app.start()

    def stop(self):
        with self.lock:
            for app in self.apps.values():
                app.stop()

    def get(self, name):
        try:
            return self.apps[name]
        except KeyError:
            raise KeyError(name) from None

    def list(self):
        return [app.snapshot() for app in self.apps.values()]

    def snapshot(self, name):
        return self.get(name).snapshot()

    def create(self, name, kind):
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise ValueError("App name must be 1-32 letters, digits, _ or -")
        if kind not in KINDS:
            raise ValueError("Type must be text or image")
        with self.lock:
            if name in self.apps:
                raise AppExists(name)
            app = self._make(name, kind)
            app.start(create=True)
            self.apps[name] = app
            self._save()
            return app.snapshot()

    def delete(self, name):
        if not isinstance(name, str) or not name:
            raise ValueError("App name required")
        with self.lock:
            app = self.apps.pop(name, None)
            if app is not None:
                app.stop()
                self._save()
            try:
                self.device.post(unpublish, name, {})
            except (OSError, ValueError, ConnectionError) as error:
                print(f"Display delete failed: {error}", flush=True)
            return {"name": name, "deleted": True}

    def update(self, name, payload):
        with self.lock:
            result = self.get(name).update(payload)
            self._save()
            return result
