"""Cached device addressing and identity-checked LAN rediscovery."""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import os
from pathlib import Path
import socket
import urllib.error

from ulanzi_tc002.http import request

if os.name == "nt":
    CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ulanzi-tc002"
else:
    CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ulanzi-tc002"
CACHE = CONFIG_DIR / "device.json"
DEFAULT_MAC = "ccc4b277a363"


def local_ipv4s():
    addresses = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("1.1.1.1", 80))
            addresses.add(sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(info[4][0])
    except OSError:
        pass
    return addresses


def local_networks():
    networks = []
    for ip in sorted(local_ipv4s()):
        address = ipaddress.ip_address(ip)
        if address.is_loopback or address.is_link_local:
            continue
        network = ipaddress.ip_network(f"{ip}/24", strict=False)
        if network not in networks:
            networks.append(network)
    return networks


def discovery_networks(config):
    specified = config.get("network")
    if specified:
        network = ipaddress.ip_network(specified, strict=False)
        if network.version != 4 or network.num_addresses > 256:
            raise ValueError("Discovery network must be IPv4 /24 or smaller")
        return [network]
    networks = local_networks()
    if not networks:
        raise ConnectionError("No LAN to scan; set TC002_DEVICE_IP or TC002_DEVICE_NETWORK")
    return networks


def probe_network(network, mac):
    def probe(address):
        try:
            data = request(f"http://{address}/getBase", timeout=0.8)
            found = str(data.get("mac", "")).lower().replace(":", "").replace("-", "")
            return str(address) if found == mac else None
        except (OSError, ValueError, AttributeError, TypeError):
            return None

    with ThreadPoolExecutor(max_workers=32) as pool:
        for address in pool.map(probe, network.hosts()):
            if address:
                return address
    return None


def discover(config):
    mac = config["mac"]
    for network in discovery_networks(config):
        address = probe_network(network, mac)
        if address:
            config["ip"] = address
            config["network"] = str(network)
            return address
    raise ConnectionError(f"Clock {mac} was not found on the LAN")


class Device:
    def __init__(self, address=None, cache=CACHE, mac=None, network=None):
        self.cache = cache
        legacy = Path.cwd() / "device.local.json"
        source = cache if cache.exists() else legacy if cache == CACHE and legacy.exists() else None
        self.config = json.loads(source.read_text()) if source else {"mac": DEFAULT_MAC}
        self.config.setdefault("mac", DEFAULT_MAC)
        self.dirty = not cache.exists() or (address is not None and address != self.config.get("ip"))
        if address:
            self.config["ip"] = str(ipaddress.IPv4Address(address))
            self.config["network"] = str(ipaddress.ip_network(f"{address}/24", strict=False))
        if mac:
            self.config["mac"] = mac
        if network:
            self.config["network"] = network
        self.address = self.config.get("ip")

    def save(self):
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.config, indent=2) + "\n")
        temporary.replace(self.cache)
        self.dirty = False

    def ensure_address(self):
        if self.address:
            return self.address
        print("No cached clock IP; scanning the LAN.", flush=True)
        self.address = discover(self.config)
        self.config["ip"] = self.address
        self.save()
        return self.address

    def post(self, sender, app, frame):
        if not self.address:
            self.ensure_address()
        try:
            result = sender(self.address, app, frame)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            print("Clock unreachable; looking for its MAC on the LAN.", flush=True)
            self.address = discover(self.config)
            result = sender(self.address, app, frame)
            self.config["ip"] = self.address
            self.save()
            return result
        if self.dirty:
            self.save()
        return result
