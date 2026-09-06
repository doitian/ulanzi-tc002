import json
import threading

from ulanzi_tc002.server.apps.text import TextApp


class Registry:
    def __init__(self, settings, device):
        self.settings = settings
        self.device = device
        self.lock = threading.Lock()
        self.apps = {"text": TextApp(device, settings.tick)}
        self._load()

    def _config_path(self):
        return self.settings.data_dir / "config.json"

    def _load(self):
        path = self._config_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for name, item in data.get("apps", {}).items():
            app = self.apps.get(name)
            if app is not None and isinstance(item, dict) and "enabled" in item:
                app.enabled = bool(item["enabled"])

    def _save(self):
        path = self._config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"apps": {name: {"enabled": app.enabled} for name, app in self.apps.items()}}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def start(self):
        with self.lock:
            for app in self.apps.values():
                if app.enabled:
                    app.start()

    def stop(self):
        with self.lock:
            for app in self.apps.values():
                widget = getattr(app, "widget", None)
                if widget is not None:
                    widget.close()

    def get(self, name):
        try:
            return self.apps[name]
        except KeyError:
            raise KeyError(name) from None

    def list(self):
        return [app.snapshot() for app in self.apps.values()]

    def snapshot(self, name):
        return self.get(name).snapshot()

    def enable(self, name):
        with self.lock:
            app = self.get(name)
            if not app.enabled:
                app.start()
            self._save()
            return app.snapshot()

    def disable(self, name):
        with self.lock:
            app = self.get(name)
            if app.enabled:
                app.stop()
            self._save()
            return app.snapshot()
