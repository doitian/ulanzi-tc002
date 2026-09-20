import io
import json
import signal
import subprocess
import unittest
from unittest.mock import patch

from ulanzi_tc002.client.agent_berth import parse_list, read_list
from ulanzi_tc002.client.badge import badge_image
from ulanzi_tc002.client.cli import main
from ulanzi_tc002.client.watch import combined_status


def session(session_id, status, provider="codex"):
    return {
        "provider": provider, "session_id": session_id, "status": status,
        "source": "cli", "kind": "hook", "cmdline": [], "last_report_ms": 0,
    }


class AgentBerthListTests(unittest.TestCase):
    def test_groups_sessions_by_provider_and_maps_statuses(self):
        states, diagnostics = parse_list([
            session("s1", "waiting"),
            session("s2", "working", "Claude"),
            session("s3", "done"),
            session("s4", "idle", "OpenCode"),
            session("s5", "working", "grok"),
            session("s6", "waiting", "pi"),
            session("s7", "working"),
        ])
        self.assertEqual(states, [
            ("opencode", "idle", 1, {"ask": 0, "run": 0, "idle": 1}),
            ("claude", "run", 1, {"ask": 0, "run": 1, "idle": 0}),
            ("codex", "ask", 1, {"ask": 1, "run": 1, "idle": 1}),
            ("grok", "run", 1, {"ask": 0, "run": 1, "idle": 0}),
            ("pi", "ask", 1, {"ask": 1, "run": 0, "idle": 0}),
        ])
        self.assertEqual(diagnostics, ())

    def test_duplicate_session_uses_last_status(self):
        states, _ = parse_list([session("s1", "working"), session("s1", "done")])
        self.assertEqual(states, [("codex", "idle", 1, {"ask": 0, "run": 0, "idle": 1})])

    def test_empty_list(self):
        self.assertEqual(parse_list([]), ([], ()))

    def test_unsupported_provider_is_skipped_with_diagnostic(self):
        states, diagnostics = parse_list([
            session("s1", "working", "Gemini"),
            session("s2", "working", "codex"),
        ])
        self.assertEqual(states, [("codex", "run", 1, {"ask": 0, "run": 1, "idle": 0})])
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("gemini", diagnostics[0])

    def test_malformed_payloads_are_rejected(self):
        for payload in (
            None, {}, "json", session("s1", "working"),
            [None], [{}], [session("s1", "working", "")],
            [session("", "working")], [session("s1", "unknown")],
            [{**session("s1", "working"), "provider": 1}],
            [{**session("s1", "working"), "session_id": 1}],
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_list(payload)

    def test_reads_json_without_a_shell(self):
        result = subprocess.CompletedProcess([], 0, json.dumps([session("s2", "working")]), "")
        with patch("ulanzi_tc002.client.agent_berth.subprocess.run", return_value=result) as run:
            self.assertEqual(read_list()[0][0][:3], ("codex", "run", 1))
        self.assertEqual(run.call_args.args, (["agent-berth", "list", "--json"],))
        self.assertEqual(run.call_args.kwargs["timeout"], 5)
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_command_and_api_errors_are_actionable(self):
        for error, message in ((FileNotFoundError(), "not found on PATH"),
                               (subprocess.TimeoutExpired("agent-berth", 5), "timed out")):
            with self.subTest(error=error):
                with patch("ulanzi_tc002.client.agent_berth.subprocess.run", side_effect=error):
                    with self.assertRaisesRegex(ValueError, message):
                        read_list()
        for code, stdout, stderr, message in (
            (1, "", "server unreachable", "server unreachable"),
            (1, "connection failed", "", "connection failed"),
            (1, "", "", "exit code 1"),
            (0, "not json", "", "Invalid JSON"),
            (0, "{}", "", "expected a JSON array"),
            (0, json.dumps([session("s1", "unknown")]), "", "Invalid agent-berth status"),
        ):
            with self.subTest(code=code, stdout=stdout, stderr=stderr):
                result = subprocess.CompletedProcess([], code, stdout, stderr)
                with patch("ulanzi_tc002.client.agent_berth.subprocess.run", return_value=result):
                    with self.assertRaisesRegex(ValueError, message):
                        read_list()


class CombinedStatusTests(unittest.TestCase):
    def test_sums_and_follows_priority(self):
        ask, count, counts = combined_status([
            ("opencode", "ask", 1, {"ask": 1, "run": 2, "idle": 0}),
            ("codex", "run", 3, {"ask": 0, "run": 3, "idle": 4}),
        ])
        self.assertEqual((ask, count), ("ask", 1))
        self.assertEqual(counts, {"ask": 1, "run": 5, "idle": 4})
        run, count, counts = combined_status([
            ("opencode", "run", 2, {"ask": 0, "run": 2, "idle": 1}),
            ("claude", "idle", 3, {"ask": 0, "run": 0, "idle": 3}),
        ])
        self.assertEqual((run, count), ("run", 2))
        self.assertEqual(counts, {"ask": 0, "run": 2, "idle": 4})
        idle, count, counts = combined_status([
            ("opencode", "idle", 1, {"ask": 0, "run": 0, "idle": 1}),
            ("grok", "idle", 0, {"ask": 0, "run": 0, "idle": 0}),
        ])
        self.assertEqual((idle, count), ("idle", 1))
        self.assertEqual(counts, {"ask": 0, "run": 0, "idle": 1})


class AgentBerthWatchTests(unittest.TestCase):
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
        result = subprocess.CompletedProcess([], 0, json.dumps([
            session("s1", "waiting"), session("s2", "working", "claude"),
            session("s3", "working", "claude"),
        ]), "")
        with patch("ulanzi_tc002.client.agent_berth.subprocess.run", return_value=result):
            main(["watch", "agents", "--once"])
        self.assertEqual(self.updates(), [(name, badge_image(kind, count, name)) for name, kind, count in (
            ("claude", "run", 2), ("codex", "ask", 1), ("agents", "ask", 1),
        )])
        calls = self.request.call_args_list
        created = [call.kwargs["json_body"]["name"] for call in calls if call.args[0].endswith("/api/apps")]
        deleted = [call.args[0].rsplit("/", 1)[-1] for call in calls if call.kwargs["method"] == "DELETE"]
        self.assertEqual(created, ["claude", "codex", "agents"])
        self.assertEqual(deleted, ["agents", "codex", "claude"])
        self.assertIn("agents ASK 1 (ask=1 run=2 idle=0)", self.output.getvalue())

    def test_polls_and_updates_changed_counts(self):
        busy = parse_list([session("s1", "working")])
        done = parse_list([session("s1", "done")])
        empty = parse_list([])
        with patch("ulanzi_tc002.client.agent_berth.read_list", side_effect=[busy, busy, done, empty, busy]) as read, \
                patch("ulanzi_tc002.client.watch.time.sleep", side_effect=[None] * 4 + [KeyboardInterrupt]) as sleep:
            with self.assertRaises(KeyboardInterrupt):
                main(["watch", "agents", "--interval", "0.25"])
        self.assertEqual(read.call_count, 5)
        self.assertTrue(all(call.args == (0.25,) for call in sleep.call_args_list))
        self.assertEqual(self.updates(), [(name, badge_image(kind, count, name)) for name, kind, count in (
            ("codex", "run", 1), ("agents", "run", 1),
            ("codex", "idle", 1), ("agents", "idle", 1), ("agents", "idle", 0),
            ("codex", "run", 1), ("agents", "run", 1),
        )])
        deleted = [call.args[0].rsplit("/", 1)[-1] for call in self.request.call_args_list if call.kwargs["method"] == "DELETE"]
        self.assertEqual(deleted, ["codex", "codex", "agents"])
        self.assertIn("No supported agents reported by agent-berth", self.output.getvalue())

    def test_diagnostic_is_printed_only_when_changed(self):
        snapshot = parse_list([session("s1", "working", "gemini")])
        with patch("ulanzi_tc002.client.agent_berth.read_list", side_effect=[snapshot, snapshot]), \
                patch("ulanzi_tc002.client.watch.time.sleep", side_effect=[None, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                main(["watch", "agents"])
        self.assertEqual(self.errors.getvalue().count("Skipping agent-berth provider gemini"), 1)
        self.assertEqual(self.updates(), [("agents", badge_image("idle", 0, "agents"))])

    def test_empty_once_keeps_zero_summary_until_cleanup(self):
        with patch("ulanzi_tc002.client.agent_berth.read_list", return_value=parse_list([])):
            main(["watch", "agents", "--once"])
        self.assertEqual(self.updates(), [("agents", badge_image("idle", 0, "agents"))])
        calls = self.request.call_args_list
        self.assertEqual([call.kwargs["method"] for call in calls], ["POST", "POST", "DELETE"])
        self.assertEqual(calls[0].kwargs["json_body"], {"name": "agents", "type": "image"})
        self.assertTrue(calls[-1].args[0].endswith("/api/apps/agents"))

    def test_startup_failure_does_not_create_apps(self):
        with patch("ulanzi_tc002.client.agent_berth.read_list", side_effect=ValueError("agent-berth not found")):
            with self.assertRaisesRegex(ValueError, "agent-berth not found"):
                main(["watch", "agents", "--once"])
        self.request.assert_not_called()

    def test_connection_loss_cleans_up_without_reporting_idle(self):
        busy = parse_list([session("s1", "working")])
        with patch("ulanzi_tc002.client.agent_berth.read_list", side_effect=[busy, ValueError("server unreachable")]), \
                patch("ulanzi_tc002.client.watch.time.sleep"):
            with self.assertRaisesRegex(ValueError, "server unreachable"):
                main(["watch", "agents"])
        self.assertEqual([call.kwargs["method"] for call in self.request.call_args_list[-2:]], ["DELETE", "DELETE"])
        self.assertNotIn("IDLE", self.output.getvalue())

    def test_rejected_badge_cleans_up_created_app(self):
        self.request.return_value = {"accepted": False}
        with patch("ulanzi_tc002.client.agent_berth.read_list", return_value=parse_list([session("s1", "working")])):
            with self.assertRaisesRegex(ValueError, "Server rejected update"):
                main(["watch", "agents", "--once"])
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
                patch("ulanzi_tc002.client.agent_berth.read_list", return_value=parse_list([session("s1", "working")])), \
                patch("ulanzi_tc002.client.watch.time.sleep", side_effect=stop):
            with self.assertRaises(SystemExit) as error:
                main(["watch", "agents"])
        self.assertEqual(error.exception.code, 0)
        self.assertEqual(handlers[signal.SIGTERM], signal.SIG_DFL)
        self.assertEqual(handlers[signal.SIGINT], signal.SIG_DFL)
        self.assertEqual([call.kwargs["method"] for call in self.request.call_args_list[-2:]], ["DELETE", "DELETE"])

    def test_rejects_invalid_intervals_before_polling(self):
        for interval in ("0", "-1", "nan", "inf"):
            with self.subTest(interval=interval):
                with patch("ulanzi_tc002.client.agent_berth.read_list") as read:
                    with self.assertRaises(SystemExit) as error:
                        main(["watch", "agents", "--interval", interval])
                    self.assertEqual(error.exception.code, 2)
                    read.assert_not_called()
        self.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
