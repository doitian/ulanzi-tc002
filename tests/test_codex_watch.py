import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from ulanzi_tc002.client.badge import BLACK, CODEX_OUTER, HEIGHT, OPENCODE_OUTER, WIDTH, compose
from ulanzi_tc002.client.bridge import Bridge, BridgeStore
from ulanzi_tc002.client.cli import main
from ulanzi_tc002.client.codex import (
    apply_hook,
    hooks_path,
    install_hooks,
    remove_hooks,
    reports,
    script_path,
    script_source,
    source_for,
)


def hook(sid, name, **extra):
    payload = {"session_id": sid, "hook_event_name": name}
    payload.update(extra)
    return payload


def write_session(root, name, originator, session_id, extra_id=None):
    path = Path(root) / f"{name}.jsonl"
    payload = {"session_id": session_id, "originator": originator}
    if extra_id is not None:
        payload["id"] = extra_id
    path.write_text(json.dumps({"type": "session_meta", "payload": payload}) + "\n", encoding="utf-8")
    return path


class CodexHookTests(unittest.TestCase):
    def test_desktop_and_cli_aggregate(self):
        sessions = {}
        desktop = {"desk-1"}
        apply_hook(sessions, hook("desk-1", "UserPromptSubmit"), desktop)
        apply_hook(sessions, hook("cli-1", "PermissionRequest"), desktop)
        kind = reports(sessions)
        by_id = {item["id"]: item for item in kind}
        self.assertEqual(by_id["desktop"]["status"], {"desk-1": "busy"})
        self.assertEqual(by_id["cli"]["status"], {"cli-1": "idle"})
        self.assertEqual(by_id["cli"]["blocking"], ["cli-1"])

    def test_switch_prunes_idle_keeps_run_and_ask(self):
        sessions = {}
        apply_hook(sessions, hook("old", "UserPromptSubmit"), set())
        apply_hook(sessions, hook("old", "Stop"), set())
        apply_hook(sessions, hook("run", "UserPromptSubmit"), set())
        apply_hook(sessions, hook("ask", "PermissionRequest"), set())
        apply_hook(sessions, hook("fresh", "SessionStart"), set())
        self.assertNotIn("old", sessions)
        self.assertEqual(sessions["run"]["status"], "busy")
        self.assertTrue(sessions["ask"]["blocking"])
        apply_hook(sessions, hook("fresh", "UserPromptSubmit"), set())
        apply_hook(sessions, hook("fresh", "Stop"), set())
        self.assertNotIn("old", sessions)
        self.assertEqual(set(sessions), {"run", "ask", "fresh"})
        self.assertEqual(sessions["fresh"]["status"], "idle")

    def test_idle_child_drops_and_other_source_stays(self):
        sessions = {}
        desktop = {"desk-1"}
        apply_hook(sessions, hook("desk-1", "UserPromptSubmit"), desktop)
        apply_hook(sessions, hook("desk-1", "Stop"), desktop)
        apply_hook(sessions, hook("cli-1", "UserPromptSubmit"), desktop)
        apply_hook(sessions, hook("cli-1", "Stop"), desktop)
        apply_hook(sessions, hook("cli-1", "UserPromptSubmit", agent_id="a1"), desktop)
        apply_hook(sessions, hook("cli-1", "SubagentStop", agent_id="a1"), desktop)
        self.assertNotIn("cli-1:a1", sessions)
        self.assertEqual(set(sessions), {"desk-1", "cli-1"})

    def test_originator_marks_desktop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_session(tmp, "desk", "Codex Desktop", "s")
            self.assertEqual(source_for(hook("s", "Stop", transcript_path=str(path)), set()), "desktop")
        self.assertEqual(source_for(hook("s", "Stop"), set()), "cli")

    def test_stop_clears_ask_and_session_end_drops(self):
        sessions = {}
        apply_hook(sessions, hook("s", "UserPromptSubmit"), set())
        apply_hook(sessions, hook("s", "PermissionRequest"), set())
        apply_hook(sessions, hook("s", "Stop"), set())
        self.assertEqual(sessions["s"], {"status": "idle", "blocking": False, "source": "cli"})
        apply_hook(sessions, hook("s", "SessionEnd"), set())
        self.assertEqual(sessions, {})

    def test_interrupt_idles_like_stop(self):
        sessions = {}
        apply_hook(sessions, hook("s", "UserPromptSubmit"), set())
        apply_hook(sessions, hook("s", "Interrupt"), set())
        self.assertEqual(sessions["s"]["status"], "idle")


class CodexBridgeTests(unittest.TestCase):
    def test_hooks_aggregate_and_stay_fresh(self):
        store = BridgeStore(stale=5, desktop_ids={"desk-1"})
        store.update("codex", hook("desk-1", "UserPromptSubmit"))
        store.update("codex", hook("cli-1", "UserPromptSubmit"))
        store.update("codex", hook("cli-1", "Stop"))
        kind, count, counts = store.snapshot("codex")
        self.assertEqual((kind, count), ("run", 1))
        self.assertEqual(counts, {"ask": 0, "run": 1, "idle": 1})
        kind, count, counts = store.snapshot("codex", now=store.instances[("codex", "desktop")]["updated"] + 6)
        self.assertEqual((kind, count), ("run", 1))

    def test_http_hook_post(self):
        store = BridgeStore(desktop_ids={"desk-1"})
        bridge = Bridge("127.0.0.1", 0, store, {"codex"})
        bridge.start()
        try:
            request = Request(
                bridge.url + "/providers/codex",
                data=json.dumps(hook("desk-1", "PermissionRequest")).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 204)
            kind, count, counts = store.snapshot("codex")
            self.assertEqual((kind, count), ("ask", 1))
            self.assertEqual(counts["ask"], 1)
        finally:
            bridge.stop()


class CodexBadgeTests(unittest.TestCase):
    def test_logo_uses_codex_color(self):
        pixels = compose("idle", 0, "codex")
        self.assertEqual(len(pixels), HEIGHT)
        self.assertTrue(all(len(row) == WIDTH for row in pixels))
        colors = {pixel for row in pixels for pixel in row}
        self.assertIn(CODEX_OUTER, colors)
        self.assertNotIn(OPENCODE_OUTER, colors)
        self.assertIn(BLACK, colors)

    def test_provider_logos_share_center(self):
        def center(pixels, color):
            xs = [x for row in pixels for x, pixel in enumerate(row) if pixel == color]
            ys = [y for y, row in enumerate(pixels) for pixel in row if pixel == color]
            return (min(xs) + max(xs), min(ys) + max(ys))
        opencode = compose("idle", 0, "opencode")
        codex = compose("idle", 0, "codex")
        self.assertEqual(center(opencode, OPENCODE_OUTER), center(codex, CODEX_OUTER))


class CodexCliTests(unittest.TestCase):
    def test_install_merges_and_remove_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = {"CODEX_HOME": tmp}
            existing = {
                "description": "user hooks",
                "hooks": {
                    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}],
                },
            }
            hooks_path(environ).write_text(json.dumps(existing), encoding="utf-8")
            dest = install_hooks("http://127.0.0.1:8010", environ)
            data = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(data["hooks"]["PreToolUse"][0]["matcher"], "Bash")
            self.assertTrue(script_path(environ).exists())
            source = script_path(environ).read_text(encoding="utf-8")
            self.assertIn("http://127.0.0.1:8010", source)
            self.assertTrue(any(
                "tc002-watch.py" in str(handler.get("command") or "")
                for group in data["hooks"]["SessionStart"]
                for handler in group.get("hooks", [])
            ))
            install_hooks("http://127.0.0.1:8010", environ)
            again = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(sum(1 for group in again["hooks"]["Stop"] if any(
                "tc002-watch.py" in str(handler.get("command") or "") for handler in group.get("hooks", [])
            )), 1)
            remove_hooks(environ)
            leftover = json.loads(hooks_path(environ).read_text(encoding="utf-8"))
            self.assertEqual(leftover["hooks"]["PreToolUse"][0]["matcher"], "Bash")
            self.assertNotIn("SessionStart", leftover.get("hooks", {}))
            self.assertFalse(script_path(environ).exists())

    @patch("ulanzi_tc002.client.config.load_client_config", return_value={})
    @patch("ulanzi_tc002.client.cli.request")
    def test_once_installs_hooks_creates_app_and_cleans_up(self, cli_request, _config):
        cli_request.return_value = {"accepted": True, "name": "codex", "deleted": True}
        with tempfile.TemporaryDirectory() as tmp:
            environ = {**os.environ, "CODEX_HOME": tmp}
            stdout = io.StringIO()
            with patch.dict(os.environ, environ, clear=True), patch("sys.stdout", stdout):
                main(["watch", "agents", "--providers", "codex", "--once", "--bridge-port", "0"])
                self.assertFalse(hooks_path(environ).exists())
                self.assertFalse(script_path(environ).exists())
            methods = [call.kwargs["method"] for call in cli_request.call_args_list]
            bodies = [call.kwargs.get("json_body") for call in cli_request.call_args_list]
            paths = [call.args[0] for call in cli_request.call_args_list]
            self.assertEqual(methods[0], "POST")
            self.assertEqual(bodies[0], {"name": "codex", "type": "image"})
            self.assertTrue(paths[0].endswith("/api/apps"))
            self.assertEqual(methods[1], "POST")
            self.assertTrue(paths[1].endswith("/api/apps/codex"))
            self.assertTrue(bodies[1]["image"].startswith("data:image/png;base64,"))
            self.assertEqual(methods[-1], "DELETE")
            self.assertTrue(paths[-1].endswith("/api/apps/codex"))
            self.assertIn("codex IDLE", stdout.getvalue())
            self.assertNotIn("IDLE 0", stdout.getvalue())

    def test_script_source_rewrites_bridge_url(self):
        source = script_source("http://127.0.0.1:8010")
        self.assertIn("http://127.0.0.1:8010", source)
        self.assertNotIn("http://127.0.0.1:8009", source)


if __name__ == "__main__":
    unittest.main()
