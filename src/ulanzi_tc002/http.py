"""HTTP helper: optional proxy, skipped for LAN destinations."""
import ipaddress
import json
import os
import socket
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener, proxy_bypass

LAN_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fc00::/7"),
)


def _is_lan_ip(address):
    return any(address in network for network in LAN_NETWORKS)


def host_ips(host):
    host = host.strip("[]")
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    addresses = []
    try:
        for info in socket.getaddrinfo(host, None):
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
    except OSError:
        return []
    return addresses


def is_lan_host(host):
    if not host:
        return False
    if host.strip("[]").lower() == "localhost":
        return True
    addresses = host_ips(host)
    return any(_is_lan_ip(address) for address in addresses)


def configured_proxy(proxy=None):
    if proxy is not None:
        return proxy or None
    for name in ("TC002_HTTP_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        value = os.environ.get(name)
        if value:
            return value
    return None


def proxy_handler_for(host, proxy=None):
    proxy = configured_proxy(proxy)
    if not proxy or (host and (is_lan_host(host) or proxy_bypass(host))):
        return ProxyHandler({})
    return ProxyHandler({"http": proxy, "https": proxy})


def request(url, method="GET", json_body=None, headers=None, timeout=10, token=None, proxy=None):
    headers = dict(headers or {})
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    if token:
        headers.setdefault("Authorization", f"Bearer {token}")
    host = urlparse(url).hostname
    request_obj = Request(url, data=data, headers=headers, method=method)
    opener = build_opener(proxy_handler_for(host, proxy))
    try:
        with opener.open(request_obj, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body) if body else {}
        except ValueError:
            payload = {}
        detail = payload.get("error") or payload.get("detail") or body or str(error)
        if not isinstance(detail, str):
            detail = json.dumps(detail)
        raise ValueError(detail) from error
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        raise ValueError(f"Unexpected response: {body[:200]}")
