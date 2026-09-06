import os
from pathlib import Path
import tomllib
from urllib.parse import urlparse, urlunparse

DEFAULT_URL = "http://127.0.0.1:8008"


def config_path():
    override = os.environ.get("TC002_CLIENT_CONFIG")
    if override:
        return Path(override)
    root = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(root) / "ulanzi-tc002" / "config.toml"


def load_client_config(path=None):
    path = Path(path) if path is not None else config_path()
    if not path.is_file():
        return {}
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    if not isinstance(data, dict):
        raise ValueError("Client config must be a TOML table")
    section = data["server"] if isinstance(data.get("server"), dict) else data
    config = {}
    url = section.get("url")
    if url is not None:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("Client config 'url' must be a non-empty string")
        config["url"] = url.strip()
    token = section.get("token")
    if token is not None:
        if not isinstance(token, str):
            raise ValueError("Client config 'token' must be a string")
        config["token"] = token
    return config


def _first(*values):
    for value in values:
        if value is not None and value != "":
            return value
    return None


def resolve_endpoint(url=None, host=None, port=None, token=None, config=None, environ=None):
    environ = os.environ if environ is None else environ
    config = load_client_config() if config is None else config
    url = _first(url, environ.get("TC002_SERVER_URL"), config.get("url"), DEFAULT_URL)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Server URL must be http(s) with a host")
    host = _first(host, environ.get("TC002_SERVER_HOST"), parsed.hostname)
    env_port = environ.get("TC002_SERVER_PORT")
    if port is None and env_port not in (None, ""):
        port = int(env_port)
    if port is None:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise ValueError("Server port must be 1..65535")
    hostname = f"[{host}]" if ":" in host and not host.startswith("[") else host
    netloc = f"{hostname}:{port}"
    base = urlunparse((parsed.scheme, netloc, (parsed.path or "").rstrip("/"), "", "", ""))
    if token is None:
        token = environ["TC002_TOKEN"] if "TC002_TOKEN" in environ else config.get("token")
    return {"url": base, "token": token or None, "host": host, "port": port}
