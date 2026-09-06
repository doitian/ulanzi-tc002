import sys
import urllib.request

BRIDGE_URL = "http://127.0.0.1:8009"


def main():
    req = urllib.request.Request(
        BRIDGE_URL.rstrip("/") + "/providers/grok",
        data=sys.stdin.buffer.read(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=1).read()
    except Exception:
        pass


if __name__ == "__main__":
    main()
