from importlib.resources import files
import os
from pathlib import Path

EXTENSION_NAME = "tc002-watch.ts"
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8009"


def config_dir(environ=None):
    environ = os.environ if environ is None else environ
    override = environ.get("PI_CODING_AGENT_DIR")
    if override:
        return Path(override)
    return Path.home() / ".pi" / "agent"


def extension_path(environ=None):
    return config_dir(environ) / "extensions" / EXTENSION_NAME


def extension_source(bridge_url=DEFAULT_BRIDGE_URL):
    text = files("ulanzi_tc002.plugins").joinpath("pi.ts").read_text(encoding="utf-8")
    return text.replace(DEFAULT_BRIDGE_URL, bridge_url.rstrip("/"))


def install_extension(bridge_url=DEFAULT_BRIDGE_URL, environ=None):
    dest = extension_path(environ)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(extension_source(bridge_url), encoding="utf-8", newline="\n")
    return dest


def remove_extension(environ=None):
    extension_path(environ).unlink(missing_ok=True)
