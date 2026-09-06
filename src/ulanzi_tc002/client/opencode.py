from importlib.resources import files
import os
from pathlib import Path

RUNNING = {"busy", "retry"}
PLUGIN_NAME = "tc002-watch.js"
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8009"


def plugin_dir(environ=None):
    environ = os.environ if environ is None else environ
    root = environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(root) / "opencode" / "plugins"


def plugin_path(environ=None):
    return plugin_dir(environ) / PLUGIN_NAME


def plugin_source(bridge_url=DEFAULT_BRIDGE_URL):
    text = files("ulanzi_tc002.plugins").joinpath("opencode.js").read_text(encoding="utf-8")
    return text.replace(DEFAULT_BRIDGE_URL, bridge_url.rstrip("/"))


def install_plugin(bridge_url=DEFAULT_BRIDGE_URL, environ=None):
    dest = plugin_path(environ)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(plugin_source(bridge_url), encoding="utf-8", newline="\n")
    return dest


def remove_plugin(environ=None):
    plugin_path(environ).unlink(missing_ok=True)


def summarize(status_by_id, blocking):
    blocking = set(blocking)
    ask = len(blocking)
    run = sum(1 for sid, kind in status_by_id.items() if sid not in blocking and kind in RUNNING)
    idle = sum(1 for sid, kind in status_by_id.items() if sid not in blocking and kind == "idle")
    counts = {"ask": ask, "run": run, "idle": idle}
    if ask:
        return "ask", ask, counts
    if run:
        return "run", run, counts
    return "idle", idle, counts
