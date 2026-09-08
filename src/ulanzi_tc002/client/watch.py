from contextlib import ExitStack
import queue
import signal
import sys
import threading

from ulanzi_tc002.client.badge import badge_image
from ulanzi_tc002.client.bridge import Bridge, BridgeStore
from ulanzi_tc002.client.claude import install_hooks, list_agents, remove_hooks
from ulanzi_tc002.client.codex import install_hooks as install_codex_hooks, remove_hooks as remove_codex_hooks
from ulanzi_tc002.client.grok import install_hooks as install_grok_hooks, remove_hooks as remove_grok_hooks
from ulanzi_tc002.client.opencode import install_plugin, remove_plugin

KNOWN_PROVIDERS = ("opencode", "claude", "codex", "grok")


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
    label = f"{name} {kind.upper()}" if count == 0 else f"{name} {kind.upper()} {count}"
    print(f"{label} (ask={counts['ask']} run={counts['run']} idle={counts['idle']})", flush=True)


class OpencodeProvider:
    name = "opencode"

    def setup(self, bridge_url, store=None):
        install_plugin(bridge_url)

    def teardown(self):
        self.cleanup()

    @staticmethod
    def cleanup():
        remove_plugin()


class ClaudeProvider:
    name = "claude"

    def setup(self, bridge_url, store=None):
        self.store = store
        self.stop = threading.Event()
        install_hooks(bridge_url)
        if store is not None:
            rows = list_agents()
            if rows is not None:
                store.merge_agents(self.name, rows)
        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()

    def _poll(self):
        while not self.stop.wait(1):
            rows = list_agents()
            if rows is None or self.store is None:
                continue
            self.store.merge_agents(self.name, rows)

    def teardown(self):
        self.stop.set()
        if hasattr(self, "thread"):
            self.thread.join(timeout=2)
        self.cleanup()

    @staticmethod
    def cleanup():
        remove_hooks()


class CodexProvider:
    name = "codex"

    def setup(self, bridge_url, store=None):
        install_codex_hooks(bridge_url)

    def teardown(self):
        self.cleanup()

    @staticmethod
    def cleanup():
        remove_codex_hooks()


class GrokProvider:
    name = "grok"

    def setup(self, bridge_url, store=None):
        self.store = store
        self.stop = threading.Event()
        install_grok_hooks(bridge_url)
        if store is not None:
            store.reap_live(self.name)
        self.thread = threading.Thread(target=self._poll, daemon=True)
        self.thread.start()

    def _poll(self):
        while not self.stop.wait(1):
            if self.store is None:
                continue
            self.store.reap_live(self.name)

    def teardown(self):
        self.stop.set()
        if hasattr(self, "thread"):
            self.thread.join(timeout=2)
        self.cleanup()

    @staticmethod
    def cleanup():
        remove_grok_hooks()


PROVIDERS = {
    OpencodeProvider.name: OpencodeProvider,
    ClaudeProvider.name: ClaudeProvider,
    CodexProvider.name: CodexProvider,
    GrokProvider.name: GrokProvider,
}


def teardown_configs(names):
    for name in names:
        PROVIDERS[name].cleanup()


def _raise_shutdown(signum, frame):
    raise SystemExit(0)


def _bind_shutdown():
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.signal(sig, _raise_shutdown)
        except (ValueError, OSError):
            pass
    return previous


def _unbind_shutdown(previous):
    for sig, handler in previous.items():
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


class WatchProviders:
    def __init__(self, args, api, bridge, store):
        self.args = args
        self.api = api
        self.bridge = bridge
        self.store = store
        self.active = {}

    def add(self, name):
        if name in self.active:
            return f"{name} is already active"
        provider = PROVIDERS[name]()
        with ExitStack() as resources:
            ensure_app(self.api, self.args, name)
            resources.callback(delete_app, self.api, self.args, name)
            self.bridge.add_provider(name)
            resources.callback(self.bridge.remove_provider, name)
            resources.callback(provider.teardown)
            provider.setup(self.bridge.url, self.store)
            self.active[name] = resources.pop_all()
        return f"Added {name}"

    def remove(self, name):
        resources = self.active.pop(name, None)
        if resources is None:
            return f"{name} is not active"
        resources.close()
        return f"Removed {name}"

    def close(self):
        # Attempt every removal even if one provider fails to clean up.
        with ExitStack() as removals:
            for name in self.active:
                removals.callback(self.remove, name)

    def command(self, line):
        parts = line.split()
        if not parts:
            return
        if len(parts) != 2 or parts[0] not in ("a", "r"):
            raise ValueError("Commands: a PROVIDER | r PROVIDER | r all")
        action, name = parts
        if action == "r" and name == "all":
            self.close()
            return "Removed all providers"
        if name not in KNOWN_PROVIDERS:
            raise ValueError(f"Unknown provider: {name}. Choose from: {', '.join(KNOWN_PROVIDERS)}")
        return self.add(name) if action == "a" else self.remove(name)


def read_commands(stream, commands):
    try:
        for line in stream:
            commands.put(line)
    except (OSError, ValueError) as error:
        commands.put(error)
    finally:
        commands.put(None)


def watch_agents(args, api):
    store = BridgeStore()
    bridge = Bridge(args.bridge_host, args.bridge_port, store, [])
    with ExitStack() as cleanup:
        cleanup.callback(_unbind_shutdown, _bind_shutdown())
        bridge.start()
        cleanup.callback(bridge.stop)
        providers = WatchProviders(args, api, bridge, store)
        cleanup.callback(providers.close)
        for name in args.providers:
            providers.add(name)
        commands = queue.Queue()
        if not args.once:
            print("Commands: a PROVIDER | r PROVIDER | r all. Ctrl-C or EOF exits.", flush=True)
            print(f"Providers: {', '.join(KNOWN_PROVIDERS)}", flush=True)
            print(f"Active: {', '.join(providers.active) or '(none)'}", flush=True)
            threading.Thread(target=read_commands, args=(sys.stdin, commands), daemon=True).start()
        last = None
        while True:
            states = [(name, *store.snapshot(name)) for name in providers.active]
            key = tuple((name, kind, count, counts["ask"], counts["run"], counts["idle"]) for name, kind, count, counts in states)
            if key != last:
                for name, kind, count, counts in states:
                    send_badge(api, args, name, kind, count, counts)
                last = key
            if args.once:
                return
            try:
                line = commands.get(timeout=args.interval)
            except queue.Empty:
                continue
            if line is None:
                return
            if isinstance(line, Exception):
                raise line
            try:
                message = providers.command(line)
            except (OSError, ValueError) as error:
                print(f"Error: {error}", flush=True)
            else:
                if message:
                    print(message, flush=True)
                    print(f"Active: {', '.join(providers.active) or '(none)'}", flush=True)
