from contextlib import ExitStack
import queue
import signal
import sys
import threading
import time

from ulanzi_tc002.client.agent_status import summarize_counts
from ulanzi_tc002.client.badge import badge_image
from ulanzi_tc002.client.bridge import Bridge, BridgeStore
from ulanzi_tc002.client.claude import install_hooks, list_agents, remove_hooks
from ulanzi_tc002.client.codex import install_hooks as install_codex_hooks, remove_hooks as remove_codex_hooks
from ulanzi_tc002.client.grok import install_hooks as install_grok_hooks, remove_hooks as remove_grok_hooks
from ulanzi_tc002.client.opencode import install_plugin, remove_plugin
from ulanzi_tc002.client.pi import install_extension, remove_extension

AGENTS_APP = "agents"


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


def combined_status(states):
    counts = {"ask": 0, "run": 0, "idle": 0}
    for _name, _kind, _count, item in states:
        counts["ask"] += item["ask"]
        counts["run"] += item["run"]
        counts["idle"] += item["idle"]
    return summarize_counts(counts)


def provider_displays(states, *, always_summary=False):
    displays = list(states)
    if always_summary or len(states) > 1:
        displays.append((AGENTS_APP, *combined_status(states)))
    return displays


def send_badge(api, args, name, kind, count, counts):
    result = api(args, f"/api/apps/{name}", method="POST", json_body={"image": badge_image(kind, count, name)})
    if not isinstance(result, dict) or result.get("accepted") is not True:
        raise ValueError(f"Server rejected update: {result}")
    label = f"{name} {kind.upper()}" if count == 0 else f"{name} {kind.upper()} {count}"
    print(f"{label} (ask={counts['ask']} run={counts['run']} idle={counts['idle']})", flush=True)


def _delete_apps(api, args, apps):
    with ExitStack() as removals:
        for name in apps:
            removals.callback(delete_app, api, args, name)


def watch_status(args, api, source, read_status):
    with ExitStack() as cleanup:
        cleanup.callback(_unbind_shutdown, _bind_shutdown())
        states, diagnostics = read_status()
        apps = {}
        cleanup.callback(_delete_apps, api, args, apps)
        last_diagnostics = None
        was_empty = False
        while True:
            if diagnostics != last_diagnostics:
                for message in diagnostics:
                    print(f"{source}: {message}", file=sys.stderr, flush=True)
                last_diagnostics = diagnostics
            displays = provider_displays(states, always_summary=True)
            names = {name for name, *_ in displays}
            for name in list(apps):
                if name not in names:
                    delete_app(api, args, name)
                    del apps[name]
            for name, *status in displays:
                if name not in apps:
                    ensure_app(api, args, name)
                    apps[name] = None
                if status != apps[name]:
                    send_badge(api, args, name, *status)
                    apps[name] = status
            if not states and not was_empty:
                print(f"No supported agents reported by {source}", flush=True)
            was_empty = not states
            if args.once:
                return
            time.sleep(args.interval)
            states, diagnostics = read_status()


class Provider:
    poll = None

    def __init__(self):
        self.stop = threading.Event()
        self.thread = None

    def setup(self, bridge_url, store=None):
        self.install(bridge_url)
        if self.poll is not None and store is not None:
            self.poll(store)
            self.thread = threading.Thread(target=self._poll, args=(store,), daemon=True)
            self.thread.start()

    def _poll(self, store):
        while not self.stop.wait(1):
            self.poll(store)

    def teardown(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.cleanup()


class OpencodeProvider(Provider):
    name = "opencode"
    install = staticmethod(install_plugin)
    cleanup = staticmethod(remove_plugin)


class ClaudeProvider(Provider):
    name = "claude"
    install = staticmethod(install_hooks)
    cleanup = staticmethod(remove_hooks)

    def poll(self, store):
        rows = list_agents()
        if rows is not None:
            store.merge_agents(self.name, rows)


class CodexProvider(Provider):
    name = "codex"
    install = staticmethod(install_codex_hooks)
    cleanup = staticmethod(remove_codex_hooks)


class GrokProvider(Provider):
    name = "grok"
    install = staticmethod(install_grok_hooks)
    cleanup = staticmethod(remove_grok_hooks)

    def poll(self, store):
        store.reap_live(self.name)


class PiProvider(Provider):
    name = "pi"
    install = staticmethod(install_extension)
    cleanup = staticmethod(remove_extension)


PROVIDERS = {
    OpencodeProvider.name: OpencodeProvider,
    ClaudeProvider.name: ClaudeProvider,
    CodexProvider.name: CodexProvider,
    GrokProvider.name: GrokProvider,
    PiProvider.name: PiProvider,
}
KNOWN_PROVIDERS = tuple(PROVIDERS)


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
        self.summary = None

    def _sync_summary(self):
        if len(self.active) > 1:
            if self.summary is None:
                with ExitStack() as resources:
                    ensure_app(self.api, self.args, AGENTS_APP)
                    resources.callback(delete_app, self.api, self.args, AGENTS_APP)
                    self.summary = resources.pop_all()
        elif self.summary is not None:
            self.summary.close()
            self.summary = None

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
        self._sync_summary()
        return f"Added {name}"

    def remove(self, name):
        resources = self.active.pop(name, None)
        if resources is None:
            return f"{name} is not active"
        resources.close()
        self._sync_summary()
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
            displays = provider_displays(states)
            key = tuple((name, kind, count, counts["ask"], counts["run"], counts["idle"]) for name, kind, count, counts in displays)
            if key != last:
                for name, kind, count, counts in displays:
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
