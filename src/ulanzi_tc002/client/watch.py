from contextlib import ExitStack
import signal
import sys
import time

from ulanzi_tc002.client.agent_status import summarize_counts
from ulanzi_tc002.client.badge import badge_image

AGENTS_APP = "agents"
MAX_RETRY_INTERVAL = 300


def ensure_app(api, args, name):
    try:
        api(args, "/api/apps", method="POST", json_body={"name": name, "type": "image"})
    except ValueError as error:
        if str(error) != "App already exists":
            raise


def delete_app(api, args, name):
    api(args, f"/api/apps/{name}", method="DELETE")


def combined_status(states):
    counts = {"ask": 0, "run": 0, "done": 0, "idle": 0}
    for _name, _kind, _count, item in states:
        counts["ask"] += item["ask"]
        counts["run"] += item["run"]
        counts["done"] += item["done"]
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
    print(f"{label} (ask={counts['ask']} run={counts['run']} done={counts['done']} idle={counts['idle']})", flush=True)


def _delete_apps(api, args, apps):
    with ExitStack() as removals:
        for name in apps:
            removals.callback(delete_app, api, args, name)


def _poll(args, source, read_status, retry_interval):
    while True:
        try:
            states, diagnostics = read_status()
            return states, diagnostics, args.interval
        except ValueError as error:
            if args.once:
                raise
            delay = min(retry_interval, MAX_RETRY_INTERVAL)
            print(f"{source}: {error}; retrying in {delay:g} seconds", file=sys.stderr, flush=True)
            time.sleep(delay)
            retry_interval = delay * 2


def watch_status(args, api, source, read_status):
    with ExitStack() as cleanup:
        cleanup.callback(_unbind_shutdown, _bind_shutdown())
        states, diagnostics, retry_interval = _poll(args, source, read_status, args.interval)
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
            states, diagnostics, retry_interval = _poll(args, source, read_status, retry_interval)


def watch_agents(args, api):
    if args.teardown:
        from ulanzi_tc002.client.agent_berth import KNOWN_PROVIDERS
        for name in (*KNOWN_PROVIDERS, AGENTS_APP):
            delete_app(api, args, name)
            print(f"Deleted {name}", flush=True)
        return
    from ulanzi_tc002.client.agent_berth import read_list
    watch_status(args, api, "agent-berth", read_list)


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
