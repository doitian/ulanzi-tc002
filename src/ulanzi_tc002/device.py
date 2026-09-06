"""Cached device addressing and identity-checked LAN rediscovery."""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import os
from pathlib import Path
import urllib.error

from ulanzi_tc002.http import request

if os.name == "nt":
    CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ulanzi-tc002"
else:
    CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ulanzi-tc002"
CACHE = CONFIG_DIR / "device.json"
DEFAULT = {"ip": "10.31.3.197", "mac": "ccc4b277a363", "network": "10.31.3.0/24"}


def discover(config):
    network = ipaddress.ip_network(config["network"], strict=False)
    if network.version != 4 or network.num_addresses > 256:
        raise ValueError("Discovery network must be IPv4 /24 or smaller")

    def probe(address):
        try:
            data = request(f"http://{address}/getBase", timeout=0.8)
            mac = str(data.get("mac", "")).lower().replace(":", "").replace("-", "")
            return str(address) if mac == config["mac"] else None
        except (OSError, ValueError, AttributeError, TypeError):
            return None

    with ThreadPoolExecutor(max_workers=32) as pool:
        for address in pool.map(probe, network.hosts()):
            if address:
                return address
    raise ConnectionError(f"Clock {config['mac']} was not found on {network}")


class Device:
    def __init__(self, address=None, cache=CACHE, mac=None, network=None):
        self.cache = cache
        legacy = Path.cwd() / "device.local.json"
        source = cache if cache.exists() else legacy if cache == CACHE and legacy.exists() else None
        self.config = json.loads(source.read_text()) if source else dict(DEFAULT)
        self.dirty = not cache.exists() or (address is not None and address != self.config["ip"])
        if address:
            self.config["ip"] = str(ipaddress.IPv4Address(address))
            self.config["network"] = str(ipaddress.ip_network(f"{address}/24", strict=False))
        if mac:
            self.config["mac"] = mac
        if network:
            self.config["network"] = network
        self.address = self.config["ip"]

    def save(self):
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.config, indent=2) + "\n")
        temporary.replace(self.cache)
        self.dirty = False

    def post(self, sender, app, frame):
        try:
            result = sender(self.address, app, frame)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            print("Clock unreachable; looking for its MAC on the cached LAN.", flush=True)
            self.address = discover(self.config)
            result = sender(self.address, app, frame)
            self.config["ip"] = self.address
            self.save()
            return result
        if self.dirty:
            self.save()
        return result
