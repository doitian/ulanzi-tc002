import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from ulanzi_tc002.client.badge import BLACK, GROK_OUTER, HEIGHT, OPENCODE_OUTER, WIDTH, compose
from ulanzi_tc002.client.bridge import Bridge, BridgeStore
from ulanzi_tc002.client.cli import main
from ulanzi_tc002.client.grok import (
    apply_hook,
    hooks_path,
    install_hooks,
    live_ids,
    reap,
    remove_hooks,
    reports,
    script_path,
    script_source,
)
from ulanzi_tc002.client.watch import parse_providers


def hook(sid, name, **extra):
    payload = {"sessionId": sid, "hookEventName": name}
    payload.update(extra)
    return payload


class GrokHookTests(unittest.TestCase):
    def test_cli_aggregate(self):
        sessions = {}
        apply_hook(sessions, hook("cli-1", "user_prompt_submit"))
        apply_hook(sessions, hook("cli-2", "notification", notificationType="permission_prompt"))
        kind = reports(sessions)
        by_id = {item["id"]: item for item in kind}
        self.assertEqual(by_id["cli"]["status"]["cli-1"], "busy")
        self.assertEqual(by_id["cli"]["status"]["cli-2"], "idle")
        self.assertEqual(by_id["cli"]["blocking"], ["cli-2"])

    def test_switch_prunes_idle_keeps_run_and_ask(self):
        sessions = {}
        apply_hook(sessions, hook("old", "UserPromptSubmit"))
        apply_hook(sessions, hook("old", "Stop"))
        apply_hook(sessions, hook("run", "UserPromptSubmit"))
        apply_hook(sessions, hook("ask", "Notification", notificationType="permission_prompt"))
        apply_hook(sessions, hook("fresh", "SessionStart"))
        self.assertNotIn("old", sessions)
        self.assertEqual(sessions["run"]["status"], "busy")
        self.assertTrue(sessions["ask"]["blocking"])
        apply_hook(sessions, hook("fresh", "UserPromptSubmit"))
        apply_hook(sessions, hook("fresh", "Stop"))
        self.assertNotIn("old", sessions)
        self.assertEqual(set(sessions), {"run", "ask", "fresh"})
        self.assertEqual(sessions["fresh"]["status"], "idle")

    def test_subagent_events_ignored(self):
        sessions = {}
        apply_hook(sessions, hook("cli-1", "UserPromptSubmit"))
        apply_hook(sessions, hook("child", "UserPromptSubmit", subagentType="explore"))
        apply_hook(sessions, hook("child", "PreToolUse", subagentType="explore"))
        self.assertEqual(set(sessions), {"cli-1"})
        self.assertEqual(sessions["cli-1"]["status"], "busy")

    def test_reap_drops_ids_not_in_live_list(self):
        sessions = {}
        apply_hook(sessions, hook("live", "UserPromptSubmit"))
        apply_hook(sessions, hook("stale", "UserPromptSubmit"))
        reap(sessions, {"live"})
        self.assertEqual(set(sessions), {"live"})
        reap(sessions, None)
        self.assertEqual(set(sessions), {"live"})

    def test_live_ids_reads_active_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = {"GROK_HOME": tmp}
            dest = Path(tmp) / "active_sessions.json"
            dest.write_text(
                json.dumps([{"session_id": "abc"}, {"sessionId": "def"}, {"pid": 1}]) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(live_ids(environ), {"abc", "def"})
            dest.write_text("{", encoding="utf-8")
            self.assertIsNone(live_ids(environ))

    def test_stop_clears_ask_and_session_end_drops(self):
        sessions = {}
        apply_hook(sessions, hook("s", "UserPromptSubmit"))
        apply_hook(sessions, hook("s", "Notification", notificationType="permission_prompt"))
        apply_hook(sessions, hook("s", "Stop"))
        self.assertEqual(sessions["s"], {"status": "idle", "blocking": False, "source": "cli"})
        apply_hook(sessions, hook("s", "SessionEnd"))
        self.assertEqual(sessions, {})

    def test_idle_prompt_only_settles_seen(self):
        sessions = {}
        apply_hook(sessions, hook("missing", "Notification", notificationType="idle_prompt"))
        self.assertEqual(sessions, {})
        apply_hook(sessions, hook("s", "UserPromptSubmit"))
        apply_hook(sessions, hook("s", "Notification", notificationType="idle_prompt"))
        self.assertEqual(sessions["s"]["status"], "idle")


class GrokBridgeTests(unittest.TestCase):
    def test_hooks_aggregate_and_stay_fresh(self):
        store = BridgeStore(stale=5)
        store.update("grok", hook("cli-1", "UserPromptSubmit"))
        store.update("grok", hook("cli-2", "UserPromptSubmit"))
        store.update("grok", hook("cli-2", "Stop"))
        kind, count, counts = store.snapshot("grok")
        self.assertEqual((kind, count), ("run", 1))
        self.assertEqual(counts, {"ask": 0, "run": 1, "idle": 1})
        kind, count, counts = store.snapshot("grok", now=store.instances[("grok", "cli")]["updated"] + 6)
        self.assertEqual((kind, count), ("run", 1))

    def test_reap_live_drops_unknown_sessions(self):
        store = BridgeStore(stale=5)
        store.update("grok", hook("live", "UserPromptSubmit"))
        store.update("grok", hook("stale", "UserPromptSubmit"))
        with patch("ulanzi_tc002.client.grok.live_ids", return_value={"live"}):
            store.reap_live("grok")
        kind, count, counts = store.snapshot("grok")
        self.assertEqual((kind, count), ("run", 1))
        self.assertEqual(counts, {"ask": 0, "run": 1, "idle": 0})

    def test_http_hook_post(self):
        store = BridgeStore()
        bridge = Bridge("127.0.0.1", 0, store, {"grok"})
        bridge.start()
        try:
            request = Request(
                bridge.url + "/providers/grok",
                data=json.dumps(hook("cli-1", "notification", notificationType="permission_prompt")).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 204)
            kind, count, counts = store.snapshot("grok")
            self.assertEqual((kind, count), ("ask", 1))
            self.assertEqual(counts["ask"], 1)
        finally:
            bridge.stop()

    def test_command_script_posts(self):
        store = BridgeStore()
        bridge = Bridge("127.0.0.1", 0, store, {"grok"})
        bridge.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                install_hooks(bridge.url, {"GROK_HOME": tmp})
                result = subprocess.run(
                    [sys.executable, str(script_path({"GROK_HOME": tmp}))],
                    input=json.dumps(hook("cli-1", "UserPromptSubmit")).encode("utf-8"),
                    timeout=2,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0)
            kind, count, counts = store.snapshot("grok")
            self.assertEqual((kind, count), ("run", 1))
            self.assertEqual(counts["run"], 1)
        finally:
            bridge.stop()


class GrokBadgeTests(unittest.TestCase):
    def test_logo_uses_grok_color(self):
        pixels = compose("idle", 0, "grok")
        self.assertEqual(len(pixels), HEIGHT)
        self.assertTrue(all(len(row) == WIDTH for row in pixels))
        colors = {pixel for row in pixels for pixel in row}
        self.assertIn(GROK_OUTER, colors)
        self.assertNotIn(OPENCODE_OUTER, colors)
        self.assertIn(BLACK, colors)

    def test_provider_logos_share_center(self):
        def center(pixels, color):
            xs = [x for row in pixels for x, pixel in enumerate(row) if pixel == color]
            ys = [y for y, row in enumerate(pixels) for pixel in row if pixel == color]
            return (min(xs) + max(xs), min(ys) + max(ys))
        opencode = compose("idle", 0, "opencode")
        grok = compose("idle", 0, "grok")
        self.assertEqual(center(opencode, OPENCODE_OUTER), center(grok, GROK_OUTER))


class GrokCliTests(unittest.TestCase):
    def test_parse_providers_includes_codex_and_grok(self):
        self.assertEqual(parse_providers("codex,grok"), ["codex", "grok"])
        self.assertEqual(parse_providers("opencode,claude,codex,grok"), ["opencode", "claude", "codex", "grok"])

    def test_install_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = {"GROK_HOME": tmp}
            dest = install_hooks("http://127.0.0.1:8010", environ)
            data = json.loads(dest.read_text(encoding="utf-8"))
            self.assertTrue(script_path(environ).exists())
            source = script_path(environ).read_text(encoding="utf-8")
            self.assertIn("http://127.0.0.1:8010", source)
            self.assertTrue(any(
                handler.get("type") == "command" and "tc002-watch.py" in str(handler.get("command") or "")
                for group in data["hooks"]["SessionStart"]
                for handler in group.get("hooks", [])
            ))
            remove_hooks(environ)
            self.assertFalse(hooks_path(environ).exists())
            self.assertFalse(script_path(environ).exists())

    def test_script_source_rewrites_bridge_url(self):
        source = script_source("http://127.0.0.1:8010")
        self.assertIn("http://127.0.0.1:8010", source)
        self.assertNotIn("http://127.0.0.1:8009", source)

    @patch("ulanzi_tc002.client.config.load_client_config", return_value={})
    @patch("ulanzi_tc002.client.cli.request")
    def test_once_installs_hooks_creates_app_and_cleans_up(self, cli_request, _config):
        cli_request.return_value = {"accepted": True, "name": "grok", "deleted": True}
        with tempfile.TemporaryDirectory() as tmp:
            environ = {**os.environ, "GROK_HOME": tmp}
            stdout = io.StringIO()
            with patch.dict(os.environ, environ, clear=True), patch("sys.stdout", stdout):
                main(["watch", "agents", "--providers", "grok", "--once", "--bridge-port", "0"])
                self.assertFalse(hooks_path(environ).exists())
                self.assertFalse(script_path(environ).exists())
            methods = [call.kwargs["method"] for call in cli_request.call_args_list]
            bodies = [call.kwargs.get("json_body") for call in cli_request.call_args_list]
            paths = [call.args[0] for call in cli_request.call_args_list]
            self.assertEqual(methods[0], "POST")
            self.assertEqual(bodies[0], {"name": "grok", "type": "image"})
            self.assertTrue(paths[0].endswith("/api/apps"))
            self.assertEqual(methods[1], "POST")
            self.assertTrue(paths[1].endswith("/api/apps/grok"))
            self.assertTrue(bodies[1]["image"].startswith("data:image/png;base64,"))
            self.assertEqual(methods[-1], "DELETE")
            self.assertTrue(paths[-1].endswith("/api/apps/grok"))
            self.assertIn("grok IDLE", stdout.getvalue())
            self.assertNotIn("IDLE 0", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
