import time

from ulanzi_tc002.client.badge import badge_image
from ulanzi_tc002.client.bridge import Bridge, BridgeStore
from ulanzi_tc002.client.opencode import install_plugin, remove_plugin

KNOWN_PROVIDERS = ("opencode",)


def parse_providers(value):
    names = []
    for part in value.split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    if not names:
        raise ValueError("Provide at least one provider")
    unknown = [name for name in names if name not in KNOWN_PROVIDERS]
    if unknown:
        raise ValueError("Unknown provider: " + ", ".join(unknown))
    return names


def ensure_app(api, args, name):
    try:
        api(args, "/api/apps", method="POST", json_body={"name": name, "type": "image"})
    except ValueError as error:
        if str(error) != "App already exists":
            raise


def delete_app(api, args, name):
    api(args, f"/api/apps/{name}", method="DELETE")


def send_badge(api, args, name, kind, count, counts):
    result = api(args, f"/api/apps/{name}", method="POST", json_body={"image": badge_image(kind, count, name)})
    if not isinstance(result, dict) or result.get("accepted") is not True:
        raise ValueError(f"Server rejected update: {result}")
    print(
        f"{name} {kind.upper()} {count} (ask={counts['ask']} run={counts['run']} idle={counts['idle']})",
        flush=True,
    )


class OpencodeProvider:
    name = "opencode"

    def setup(self, bridge_url):
        install_plugin(bridge_url)

    def teardown(self):
        remove_plugin()


PROVIDERS = {OpencodeProvider.name: OpencodeProvider}


def watch_agents(args, api):
    providers = [PROVIDERS[name]() for name in args.providers]
    store = BridgeStore()
    bridge = Bridge(args.bridge_host, args.bridge_port, store, args.providers)
    created = []
    started = []
    try:
        bridge.start()
        for provider in providers:
            ensure_app(api, args, provider.name)
            created.append(provider.name)
            provider.setup(bridge.url)
            started.append(provider)
        last = None
        while True:
            states = [(provider.name, *store.snapshot(provider.name)) for provider in providers]
            key = tuple((name, kind, count, counts["ask"], counts["run"], counts["idle"]) for name, kind, count, counts in states)
            if key != last:
                for name, kind, count, counts in states:
                    send_badge(api, args, name, kind, count, counts)
                last = key
            if args.once:
                return
            time.sleep(args.interval)
    finally:
        for provider in reversed(started):
            provider.teardown()
        for name in reversed(created):
            delete_app(api, args, name)
        bridge.stop()
