import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from ulanzi_tc002.client.badge import BLACK, CLAUDE_OUTER, HEIGHT, OPENCODE_OUTER, WIDTH, compose
from ulanzi_tc002.client.bridge import Bridge, BridgeStore
from ulanzi_tc002.client.claude import (
    apply_agents,
    apply_hook,
    hook_url,
    install_hooks,
    remove_hooks,
    reports,
    settings_path,
    source_for,
)
from ulanzi_tc002.client.cli import main


def hook(sid, name, **extra):
    payload = {"session_id": sid, "hook_event_name": name}
    payload.update(extra)
    return payload


class ClaudeHookTests(unittest.TestCase):
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
        apply_hook(sessions, hook("child", "UserPromptSubmit", agent_id="a1"), desktop)
        apply_hook(sessions, hook("child", "Stop", agent_id="a1"), desktop)
        self.assertNotIn("child", sessions)
        self.assertEqual(set(sessions), {"desk-1", "cli-1"})

    def test_entrypoint_marks_desktop(self):
        self.assertEqual(source_for(hook("s", "Stop", entrypoint="claude-desktop"), set()), "desktop")
        self.assertEqual(source_for(hook("s", "Stop"), set()), "cli")

    def test_stop_clears_ask_and_session_end_drops(self):
        sessions = {}
        apply_hook(sessions, hook("s", "UserPromptSubmit"), set())
        apply_hook(sessions, hook("s", "PermissionRequest"), set())
        apply_hook(sessions, hook("s", "Stop"), set())
        self.assertEqual(sessions["s"], {"status": "idle", "blocking": False, "source": "cli"})
        apply_hook(sessions, hook("s", "SessionEnd"), set())
        self.assertEqual(sessions, {})

    def test_notification_ask_and_agents_busy(self):
        sessions = {}
        apply_hook(sessions, hook("s", "Notification", notification_type="permission_prompt"), set())
        self.assertTrue(sessions["s"]["blocking"])
        apply_agents(sessions, [{"sessionId": "bg", "state": "working"}])
        apply_agents(sessions, [{"id": "wait", "status": "waiting", "waitingFor": "permission prompt"}])
        by_id = {item["id"]: item for item in reports(sessions)}
        self.assertEqual(by_id["cli"]["status"]["bg"], "busy")
        self.assertIn("wait", by_id["cli"]["blocking"])

    def test_agents_without_status_keep_hook_run(self):
        sessions = {}
        apply_hook(sessions, hook("s", "PreToolUse"), set())
        apply_agents(sessions, [{"sessionId": "s", "pid": 9, "kind": "interactive"}])
        self.assertEqual(sessions["s"]["status"], "busy")
        self.assertEqual(sessions["s"]["pid"], 9)
        apply_agents(sessions, [{"sessionId": "live", "pid": 8}])
        self.assertEqual(sessions["live"]["status"], "idle")

    def test_agents_running_state_is_busy(self):
        sessions = {}
        apply_agents(sessions, [{"sessionId": "s", "state": "running"}])
        self.assertEqual(sessions["s"]["status"], "busy")

    def test_stop_with_background_work_keeps_session_running(self):
        for task_type in ("shell", "subagent", "MCP task"):
            with self.subTest(task_type=task_type):
                sessions = {}
                apply_hook(sessions, hook("s", "UserPromptSubmit"), set())
                apply_hook(sessions, hook("s", "PermissionRequest"), set())
                apply_hook(sessions, hook("s", "Stop", background_tasks=[
                    {"id": "task-1", "type": task_type, "status": "running"},
                ]), set())
                self.assertEqual(sessions["s"]["status"], "busy")
                self.assertFalse(sessions["s"]["blocking"])
                apply_agents(sessions, [{"sessionId": "s", "pid": 9}])
                apply_hook(sessions, hook("other", "SessionStart"), set())
                self.assertEqual(sessions["s"]["status"], "busy")
                apply_hook(sessions, hook("s", "Stop", background_tasks=[]), set())
                self.assertEqual(sessions["s"]["status"], "idle")

    def test_stop_without_running_tasks_is_idle(self):
        for tasks in (None, [], {}, "running", [None], [{"status": "completed"}],
                      [{"status": "failed"}], [{"status": "stopped"}]):
            with self.subTest(tasks=tasks):
                sessions = {}
                apply_hook(sessions, hook("s", "UserPromptSubmit"), set())
                apply_hook(sessions, hook("s", "Stop", background_tasks=tasks,
                                          session_crons=[{"id": "cron-1"}]), set())
                self.assertEqual(sessions["s"]["status"], "idle")


class ClaudeBridgeTests(unittest.TestCase):
    def test_manual_background_stop_becomes_idle_on_poll(self):
        store = BridgeStore(desktop_ids={"s"})
        store.update("claude", hook("s", "Stop", background_tasks=[
            {"id": "task-1", "type": "shell", "status": "running"},
            {"id": "task-2", "type": "subagent", "status": "running"},
        ]))
        # Another task still running must keep the session RUN. Repeated
        # polls must retain the fact that the foreground turn has stopped.
        for status in ("busy", "busy", None):
            row = {"sessionId": "s", "pid": 9}
            if status is not None:
                row["status"] = status
            store.merge_agents("claude", [row])
            self.assertEqual(store.snapshot("claude")[0:2], ("run", 1))
            self.assertEqual(store.hooks["claude"]["s"]["source"], "desktop")
        # The final task was stopped in Claude's UI, without a Stop hook.
        store.merge_agents("claude", [{"sessionId": "s", "pid": 9, "status": "idle"}])
        self.assertEqual(store.snapshot("claude"),
                         ("idle", 1, {"ask": 0, "run": 0, "idle": 1}))

    def test_idle_poll_does_not_clear_resumed_foreground_or_ask(self):
        for event, expected in (("UserPromptSubmit", "run"),
                                ("PreToolUse", "run"),
                                ("PostToolUse", "run"),
                                ("PermissionRequest", "ask")):
            with self.subTest(event=event):
                store = BridgeStore(desktop_ids=set())
                store.update("claude", hook("s", "Stop", background_tasks=[
                    {"id": "task-1", "type": "shell", "status": "running"},
                ]))
                store.update("claude", hook("s", event))
                store.merge_agents("claude", [{"sessionId": "s", "status": "idle"}])
                self.assertEqual(store.snapshot("claude")[0:2], (expected, 1))

    def test_unavailable_poll_keeps_background_session_running(self):
        store = BridgeStore(desktop_ids=set())
        store.update("claude", hook("s", "Stop", background_tasks=[
            {"id": "task-1", "type": "shell", "status": "running"},
        ]))
        for rows in (None, [], [{"sessionId": "s", "status": "unknown"}]):
            store.merge_agents("claude", rows)
            self.assertEqual(store.snapshot("claude")[0:2], ("run", 1))

    def test_background_only_stop_discovers_session_and_counts_once(self):
        store = BridgeStore(desktop_ids={"s"})
        store.update("claude", hook("s", "Stop", background_tasks=[
            {"id": "task-1", "type": "shell", "status": "running"},
            {"id": "task-2", "type": "subagent", "status": "running"},
        ]))
        self.assertEqual(store.snapshot("claude"),
                         ("run", 1, {"ask": 0, "run": 1, "idle": 0}))
        self.assertEqual(store.hooks["claude"]["s"]["source"], "desktop")
        store.update("claude", hook("s", "SessionEnd"))
        self.assertEqual(store.snapshot("claude"),
                         ("idle", 0, {"ask": 0, "run": 0, "idle": 0}))

    def test_hooks_aggregate_and_stay_fresh(self):
        store = BridgeStore(stale=5, desktop_ids={"desk-1"})
        store.update("claude", hook("desk-1", "UserPromptSubmit"))
        store.update("claude", hook("cli-1", "UserPromptSubmit"))
        store.update("claude", hook("cli-1", "Stop"))
        kind, count, counts = store.snapshot("claude")
        self.assertEqual((kind, count), ("run", 1))
        self.assertEqual(counts, {"ask": 0, "run": 1, "idle": 1})
        kind, count, counts = store.snapshot("claude", now=store.instances[("claude", "desktop")]["updated"] + 6)
        self.assertEqual((kind, count), ("run", 1))

    def test_http_hook_post(self):
        store = BridgeStore(desktop_ids={"desk-1"})
        bridge = Bridge("127.0.0.1", 0, store, {"claude"})
        bridge.start()
        try:
            request = Request(
                bridge.url + "/providers/claude",
                data=json.dumps(hook("desk-1", "PermissionRequest")).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 204)
            kind, count, counts = store.snapshot("claude")
            self.assertEqual((kind, count), ("ask", 1))
            self.assertEqual(counts["ask"], 1)
        finally:
            bridge.stop()

    def test_merge_agents_with_desktop_hooks(self):
        store = BridgeStore(desktop_ids={"desk-1"})
        store.update("claude", hook("desk-1", "UserPromptSubmit"))
        store.update("claude", hook("desk-1", "Stop"))
        store.merge_agents("claude", [{"sessionId": "cli-1", "state": "working", "pid": 9}])
        kind, count, counts = store.snapshot("claude")
        self.assertEqual((kind, count), ("run", 1))
        self.assertEqual(counts, {"ask": 0, "run": 1, "idle": 1})


class ClaudeBadgeTests(unittest.TestCase):
    def test_logo_uses_claude_color(self):
        pixels = compose("idle", 0, "claude")
        self.assertEqual(len(pixels), HEIGHT)
        self.assertTrue(all(len(row) == WIDTH for row in pixels))
        colors = {pixel for row in pixels for pixel in row}
        self.assertIn(CLAUDE_OUTER, colors)
        self.assertNotIn(OPENCODE_OUTER, colors)
        self.assertIn(BLACK, colors)
        claws = [y for y, row in enumerate(pixels) if row.count(CLAUDE_OUTER) >= 16]
        self.assertTrue(claws)

    def test_provider_logos_share_center(self):
        def center(pixels, color):
            xs = [x for row in pixels for x, pixel in enumerate(row) if pixel == color]
            ys = [y for y, row in enumerate(pixels) for pixel in row if pixel == color]
            return (min(xs) + max(xs), min(ys) + max(ys))
        opencode = compose("idle", 0, "opencode")
        claude = compose("idle", 0, "claude")
        self.assertEqual(center(opencode, OPENCODE_OUTER), center(claude, CLAUDE_OUTER))


class ClaudeCliTests(unittest.TestCase):
    def test_install_merges_and_remove_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = {"CLAUDE_CONFIG_DIR": tmp}
            existing = {
                "permissions": {"allow": ["Bash(git *)"]},
                "hooks": {
                    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}],
                },
                "allowedHttpHookUrls": ["http://example.test/hooks"],
            }
            settings_path(environ).write_text(json.dumps(existing), encoding="utf-8")
            dest = install_hooks("http://127.0.0.1:8010", environ)
            data = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(data["permissions"], existing["permissions"])
            self.assertEqual(data["hooks"]["PreToolUse"][0]["matcher"], "Bash")
            url = hook_url("http://127.0.0.1:8010")
            self.assertTrue(any(
                handler.get("url") == url
                for group in data["hooks"]["SessionStart"]
                for handler in group.get("hooks", [])
            ))
            self.assertIn(url, data["allowedHttpHookUrls"])
            install_hooks("http://127.0.0.1:8010", environ)
            again = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(sum(1 for group in again["hooks"]["Stop"] if any(
                handler.get("url") == url for handler in group.get("hooks", [])
            )), 1)
            remove_hooks(environ)
            leftover = json.loads(settings_path(environ).read_text(encoding="utf-8"))
            self.assertEqual(leftover["permissions"], existing["permissions"])
            self.assertEqual(leftover["hooks"]["PreToolUse"][0]["matcher"], "Bash")
            self.assertNotIn("SessionStart", leftover.get("hooks", {}))
            self.assertEqual(leftover["allowedHttpHookUrls"], ["http://example.test/hooks"])

    @patch("ulanzi_tc002.client.watch.list_agents", return_value=[])
    @patch("ulanzi_tc002.client.config.load_client_config", return_value={})
    @patch("ulanzi_tc002.client.cli.request")
    def test_once_installs_hooks_creates_app_and_cleans_up(self, cli_request, _config, _agents):
        cli_request.return_value = {"accepted": True, "name": "claude", "deleted": True}
        with tempfile.TemporaryDirectory() as tmp:
            environ = {**os.environ, "CLAUDE_CONFIG_DIR": tmp}
            stdout = io.StringIO()
            with patch.dict(os.environ, environ, clear=True), patch("sys.stdout", stdout):
                main(["watch", "agents", "--providers", "claude", "--once", "--bridge-port", "0"])
                self.assertFalse(settings_path(environ).exists())
            methods = [call.kwargs["method"] for call in cli_request.call_args_list]
            bodies = [call.kwargs.get("json_body") for call in cli_request.call_args_list]
            paths = [call.args[0] for call in cli_request.call_args_list]
            self.assertEqual(methods[0], "POST")
            self.assertEqual(bodies[0], {"name": "claude", "type": "image"})
            self.assertTrue(paths[0].endswith("/api/apps"))
            self.assertEqual(methods[1], "POST")
            self.assertTrue(paths[1].endswith("/api/apps/claude"))
            self.assertTrue(bodies[1]["image"].startswith("data:image/png;base64,"))
            self.assertEqual(methods[-1], "DELETE")
            self.assertTrue(paths[-1].endswith("/api/apps/claude"))
            self.assertIn("claude IDLE", stdout.getvalue())
            self.assertNotIn("IDLE 0", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
