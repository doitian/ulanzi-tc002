import io
import json
import signal
import subprocess
import unittest
from unittest.mock import patch

from ulanzi_tc002.client.badge import badge_image
from ulanzi_tc002.client.cli import main
from ulanzi_tc002.client.herdr import parse_status, read_status


def pane(pane_id, status, agent="codex"):
    return {
        "pane_id": pane_id, "agent": agent, "agent_status": status,
        "agent_session": {"agent": agent, "kind": "id", "value": "shared-session"},
    }


def response(*agents):
    return {"id": "cli:agent:list", "result": {"type": "agent_list", "agents": list(agents)}}


class HerdrStatusTests(unittest.TestCase):
    def test_groups_panes_by_provider_and_maps_blocked_to_ask(self):
        states, diagnostics = parse_status(response(
            pane("wW:p1", "blocked"), pane("wW:p2", "working", "Claude"),
            pane("wW:p3", "done"), pane("wW:p4", "idle", "OpenCode"),
            pane("wW:p5", "working", "grok"), pane("wW:p6", "blocked", "pi"),
            pane("wX:p1", "working"),
        ))
        self.assertEqual(states, [
            ("opencode", "idle", 1, {"ask": 0, "run": 0, "idle": 1}),
            ("claude", "run", 1, {"ask": 0, "run": 1, "idle": 0}),
            ("codex", "ask", 1, {"ask": 1, "run": 1, "idle": 1}),
            ("grok", "run", 1, {"ask": 0, "run": 1, "idle": 0}),
            ("pi", "ask", 1, {"ask": 1, "run": 0, "idle": 0}),
        ])
        self.assertEqual(diagnostics, ())

    def test_duplicate_pane_uses_last_status(self):
        states, _ = parse_status(response(pane("wW:p1", "working"), pane("wW:p1", "done")))
        self.assertEqual(states, [("codex", "idle", 1, {"ask": 0, "run": 0, "idle": 1})])

    def test_empty_response(self):
        self.assertEqual(parse_status(response()), ([], ()))

    def test_unknown_status_and_unmapped_agents_are_skipped_with_diagnostics(self):
        states, diagnostics = parse_status(response(
            pane("wW:p1", "unknown"), pane("wW:p2", "working", "Gemini"),
            pane("wW:p3", "idle", None), pane("wW:p4", "working", "Gemini"),
        ))
        self.assertEqual(states, [])
        self.assertEqual(len(diagnostics), 3)
        self.assertIn("wW:p1 (codex): agent status is unknown", diagnostics[0])
        self.assertIn("gemini", diagnostics[1])
        self.assertIn("(unnamed)", diagnostics[2])

    def test_malformed_responses_are_not_reported_as_idle(self):
        for payload in (
            None, [], {}, {"agents": []}, {"result": []},
            {"result": {"type": "snapshot", "agents": []}},
            {"result": {"type": "agent_list", "agents": {}}}, response(None),
            response(pane(1, "working")), response(pane("", "working")),
            response(pane(" ", "working")), response(pane("wW:p1", "waiting")),
            response(pane("wW:p1", None)), response(pane("wW:p1", [])),
            response(pane("wW:p1", "working", [])), response({"pane_id": "wW:p1"}),
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_status(payload)

    def test_reads_default_machine_and_session_without_a_shell(self):
        for machine, session, expected in (
            (None, None, ["herdr", "agent", "list"]),
            ("devbox", None, ["herdr", "--machine", "devbox", "agent", "list"]),
            (None, "work", ["herdr", "--session", "work", "agent", "list"]),
            ("dev box", "work", ["herdr", "--machine", "dev box", "--session", "work", "agent", "list"]),
        ):
            with self.subTest(machine=machine, session=session):
                result = subprocess.CompletedProcess([], 0, json.dumps(response(pane("wW:p2", "working"))), "")
                with patch("ulanzi_tc002.client.herdr.subprocess.run", return_value=result) as run:
                    self.assertEqual(read_status(machine, session)[0][0][:3], ("codex", "run", 1))
                self.assertEqual(run.call_args.args, (expected,))
                self.assertEqual(run.call_args.kwargs["timeout"], 5)
                self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
                self.assertEqual(run.call_args.kwargs["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_command_and_api_errors_are_actionable(self):
        for error, message in ((FileNotFoundError(), "not found on PATH"),
                               (subprocess.TimeoutExpired("herdr", 5), "timed out")):
            with self.subTest(error=error):
                with patch("ulanzi_tc002.client.herdr.subprocess.run", side_effect=error):
                    with self.assertRaisesRegex(ValueError, message):
                        read_status()
        for code, stdout, stderr, message in (
            (1, "", "server unreachable", "server unreachable"),
            (1, "connection failed", "", "connection failed"),
            (1, "", "", "exit code 1"),
            (0, "not json", "", "Invalid JSON"),
            (0, "{}", "", "expected an agent_list result"),
            (0, json.dumps({"id": "cli:agent:list", "error": {"code": "server_error", "message": "session unavailable"}}), "", "session unavailable"),
        ):
            with self.subTest(code=code, stdout=stdout, stderr=stderr):
                result = subprocess.CompletedProcess([], code, stdout, stderr)
                with patch("ulanzi_tc002.client.herdr.subprocess.run", return_value=result):
                    with self.assertRaisesRegex(ValueError, message):
                        read_status()


class HerdrWatchTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("ulanzi_tc002.client.config.load_client_config", return_value={}))
        self.output = self.enterContext(patch("sys.stdout", new_callable=io.StringIO))
        self.errors = self.enterContext(patch("sys.stderr", new_callable=io.StringIO))
        self.request = self.enterContext(patch("ulanzi_tc002.client.cli.request", return_value={"accepted": True}))

    def updates(self):
        return [(call.args[0].rsplit("/", 1)[-1], call.kwargs["json_body"]["image"])
                for call in self.request.call_args_list
                if call.kwargs["method"] == "POST" and "/api/apps/" in call.args[0]]

    def test_once_creates_badges_and_cleans_up_without_installing_hooks(self):
        result = subprocess.CompletedProcess([], 0, json.dumps(response(
            pane("wW:p1", "blocked"), pane("wW:p2", "working", "claude"),
            pane("wW:p3", "working", "claude"),
        )), "")
        with patch("ulanzi_tc002.client.herdr.subprocess.run", return_value=result), \
                patch("ulanzi_tc002.client.watch.Bridge") as bridge, \
                patch("ulanzi_tc002.client.watch.WatchProviders") as providers:
            main(["watch", "herdr", "--once"])
        bridge.assert_not_called()
        providers.assert_not_called()
        self.assertEqual(self.updates(), [(name, badge_image(kind, count, name)) for name, kind, count in (
            ("claude", "run", 2), ("codex", "ask", 1), ("agents", "ask", 1),
        )])
        calls = self.request.call_args_list
        created = [call.kwargs["json_body"]["name"] for call in calls if call.args[0].endswith("/api/apps")]
        deleted = [call.args[0].rsplit("/", 1)[-1] for call in calls if call.kwargs["method"] == "DELETE"]
        self.assertEqual(created, ["claude", "codex", "agents"])
        self.assertEqual(deleted, ["agents", "codex", "claude"])
        self.assertIn("agents ASK 1 (ask=1 run=2 idle=0)", self.output.getvalue())

    def test_polls_without_stdin_and_updates_changed_counts(self):
        busy = parse_status(response(pane("wW:p1", "working")))
        done = parse_status(response(pane("wW:p1", "done")))
        empty = parse_status(response())
        with patch("sys.stdin", io.StringIO()), \
                patch("ulanzi_tc002.client.herdr.read_status", side_effect=[busy, busy, done, empty, busy]) as read, \
                patch("ulanzi_tc002.client.watch.time.sleep", side_effect=[None] * 4 + [KeyboardInterrupt]) as sleep:
            with self.assertRaises(KeyboardInterrupt):
                main(["watch", "herdr", "--machine", "devbox", "--session", "work", "--interval", "0.25"])
        self.assertEqual(read.call_count, 5)
        self.assertTrue(all(call.args == ("devbox", "work") for call in read.call_args_list))
        self.assertTrue(all(call.args == (0.25,) for call in sleep.call_args_list))
        self.assertEqual(self.updates(), [(name, badge_image(kind, count, name)) for name, kind, count in (
            ("codex", "run", 1), ("agents", "run", 1),
            ("codex", "idle", 1), ("agents", "idle", 1), ("agents", "idle", 0),
            ("codex", "run", 1), ("agents", "run", 1),
        )])
        deleted = [call.args[0].rsplit("/", 1)[-1] for call in self.request.call_args_list if call.kwargs["method"] == "DELETE"]
        self.assertEqual(deleted, ["codex", "codex", "agents"])
        self.assertIn("No supported agents reported by herdr", self.output.getvalue())

    def test_unknown_status_diagnostic_is_printed_only_when_changed(self):
        snapshot = parse_status(response(pane("wW:p1", "unknown")))
        with patch("ulanzi_tc002.client.herdr.read_status", side_effect=[snapshot, snapshot]), \
                patch("ulanzi_tc002.client.watch.time.sleep", side_effect=[None, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                main(["watch", "herdr"])
        self.assertEqual(self.errors.getvalue().count("agent status is unknown"), 1)
        self.assertEqual(self.updates(), [("agents", badge_image("idle", 0, "agents"))])

    def test_empty_once_keeps_zero_summary_until_cleanup(self):
        with patch("ulanzi_tc002.client.herdr.read_status", return_value=parse_status(response())):
            main(["watch", "herdr", "--once"])
        self.assertEqual(self.updates(), [("agents", badge_image("idle", 0, "agents"))])
        calls = self.request.call_args_list
        self.assertEqual([call.kwargs["method"] for call in calls], ["POST", "POST", "DELETE"])
        self.assertEqual(calls[0].kwargs["json_body"], {"name": "agents", "type": "image"})
        self.assertTrue(calls[-1].args[0].endswith("/api/apps/agents"))

    def test_startup_failure_does_not_create_apps(self):
        with patch("ulanzi_tc002.client.herdr.read_status", side_effect=ValueError("server unreachable")):
            with self.assertRaisesRegex(ValueError, "server unreachable"):
                main(["watch", "herdr", "--once"])
        self.request.assert_not_called()

    def test_connection_loss_cleans_up_without_reporting_idle(self):
        busy = parse_status(response(pane("wW:p1", "working")))
        with patch("ulanzi_tc002.client.herdr.read_status", side_effect=[busy, ValueError("server unreachable")]), \
                patch("ulanzi_tc002.client.watch.time.sleep"):
            with self.assertRaisesRegex(ValueError, "server unreachable"):
                main(["watch", "herdr"])
        self.assertEqual([call.kwargs["method"] for call in self.request.call_args_list[-2:]], ["DELETE", "DELETE"])
        self.assertNotIn("IDLE", self.output.getvalue())

    def test_rejected_badge_cleans_up_created_app(self):
        self.request.return_value = {"accepted": False}
        with patch("ulanzi_tc002.client.herdr.read_status", return_value=parse_status(response(pane("wW:p1", "working")))):
            with self.assertRaisesRegex(ValueError, "Server rejected update"):
                main(["watch", "herdr", "--once"])
        self.assertEqual(self.request.call_args_list[-1].kwargs["method"], "DELETE")
        self.assertTrue(self.request.call_args_list[-1].args[0].endswith("/api/apps/codex"))

    def test_sigterm_cleans_up_and_restores_handlers(self):
        handlers = {}

        def bind(sig, handler):
            handlers[sig] = handler
            return signal.SIG_DFL

        def stop(_interval):
            handlers[signal.SIGTERM](signal.SIGTERM, None)

        with patch("ulanzi_tc002.client.watch.signal.signal", side_effect=bind), \
                patch("ulanzi_tc002.client.herdr.read_status", return_value=parse_status(response(pane("wW:p1", "working")))), \
                patch("ulanzi_tc002.client.watch.time.sleep", side_effect=stop):
            with self.assertRaises(SystemExit) as error:
                main(["watch", "herdr"])
        self.assertEqual(error.exception.code, 0)
        self.assertEqual(handlers[signal.SIGTERM], signal.SIG_DFL)
        self.assertEqual(handlers[signal.SIGINT], signal.SIG_DFL)
        self.assertEqual([call.kwargs["method"] for call in self.request.call_args_list[-2:]], ["DELETE", "DELETE"])

    def test_rejects_invalid_intervals_before_polling(self):
        for interval in ("0", "-1", "nan", "inf"):
            with self.subTest(interval=interval):
                with patch("ulanzi_tc002.client.herdr.read_status") as read:
                    with self.assertRaises(SystemExit) as error:
                        main(["watch", "herdr", "--interval", interval])
                    self.assertEqual(error.exception.code, 2)
                    read.assert_not_called()
        self.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
