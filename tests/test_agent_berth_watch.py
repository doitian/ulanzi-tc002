import io
import json
import signal
import subprocess
import unittest
from unittest.mock import patch

from ulanzi_tc002.client.agent_berth import parse_stats, read_stats
from ulanzi_tc002.client.badge import badge_image
from ulanzi_tc002.client.cli import main
from ulanzi_tc002.client.watch import combined_status


def stats(provider="codex", waiting=0, running=0, done=0, idle=0):
    return {
        "provider": provider, "waiting": waiting, "running": running,
        "done": done, "idle": idle, "total": waiting + running + done + idle,
    }


def counts(waiting=0, running=0, done=0, idle=0):
    return {"waiting": waiting, "running": running, "done": done, "idle": idle}


class AgentBerthStatsTests(unittest.TestCase):
    def test_groups_counts_by_provider(self):
        states, diagnostics = parse_stats([
            stats("codex", waiting=1, running=1, done=1),
            stats("Claude", running=1),
            stats("OpenCode", idle=1),
            stats("grok", running=1),
            stats("pi", waiting=1),
        ])
        self.assertEqual(states, [
            ("opencode", "idle", 1, counts(idle=1)),
            ("claude", "running", 1, counts(running=1)),
            ("codex", "waiting", 1, counts(waiting=1, running=1, done=1)),
            ("grok", "running", 1, counts(running=1)),
            ("pi", "waiting", 1, counts(waiting=1)),
        ])
        self.assertEqual(diagnostics, ())

    def test_duplicate_provider_uses_last_counts(self):
        states, _ = parse_stats([stats(running=1), stats(done=1)])
        self.assertEqual(states, [("codex", "done", 1, counts(done=1))])

    def test_empty_list(self):
        self.assertEqual(parse_stats([]), ([], ()))

    def test_provider_without_sessions_is_skipped(self):
        self.assertEqual(parse_stats([stats()]), ([], ()))

    def test_unsupported_provider_is_skipped_with_diagnostic(self):
        states, diagnostics = parse_stats([stats("Gemini", running=1), stats(running=1)])
        self.assertEqual(states, [("codex", "running", 1, counts(running=1))])
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("gemini", diagnostics[0])

    def test_malformed_payloads_are_rejected(self):
        for payload in (
            None, {}, "json", stats(running=1),
            [None], [{}], [stats("", running=1)],
            [{**stats(running=1), "provider": 1}],
            [{**stats(), "running": "1"}],
            [{**stats(), "running": 1.5}],
            [{**stats(), "running": True}],
            [{**stats(), "running": -1}],
            [{key: value for key, value in stats().items() if key != "waiting"}],
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_stats(payload)

    def test_reads_json_without_a_shell(self):
        result = subprocess.CompletedProcess([], 0, json.dumps([stats(running=1)]), "")
        with patch("ulanzi_tc002.client.agent_berth.subprocess.run", return_value=result) as run:
            self.assertEqual(read_stats()[0][0][:3], ("codex", "running", 1))
        self.assertEqual(run.call_args.args, (["agent-berth", "stats", "--json"],))
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
                        read_stats()
        for code, stdout, stderr, message in (
            (1, "", "server unreachable", "server unreachable"),
            (1, "connection failed", "", "connection failed"),
            (1, "", "", "exit code 1"),
            (0, "not json", "", "Invalid JSON"),
            (0, "{}", "", "expected a JSON array"),
            (0, json.dumps([{**stats(), "running": -1}]), "", "Invalid agent-berth counts"),
        ):
            with self.subTest(code=code, stdout=stdout, stderr=stderr):
                result = subprocess.CompletedProcess([], code, stdout, stderr)
                with patch("ulanzi_tc002.client.agent_berth.subprocess.run", return_value=result):
                    with self.assertRaisesRegex(ValueError, message):
                        read_stats()


class CombinedStatusTests(unittest.TestCase):
    def test_sums_and_follows_priority(self):
        waiting, count, total = combined_status([
            ("opencode", "waiting", 1, counts(waiting=1, running=2)),
            ("codex", "running", 3, counts(running=3, idle=4)),
        ])
        self.assertEqual((waiting, count), ("waiting", 1))
        self.assertEqual(total, counts(waiting=1, running=5, idle=4))
        running, count, total = combined_status([
            ("opencode", "running", 2, counts(running=2, done=1, idle=1)),
            ("claude", "idle", 3, counts(idle=3)),
        ])
        self.assertEqual((running, count), ("running", 2))
        self.assertEqual(total, counts(running=2, done=1, idle=4))
        done, count, total = combined_status([
            ("opencode", "done", 2, counts(done=2, idle=1)),
            ("claude", "idle", 3, counts(idle=3)),
        ])
        self.assertEqual((done, count), ("done", 2))
        self.assertEqual(total, counts(done=2, idle=4))
        idle, count, total = combined_status([
            ("opencode", "idle", 1, counts(idle=1)),
            ("grok", "idle", 0, counts()),
        ])
        self.assertEqual((idle, count), ("idle", 1))
        self.assertEqual(total, counts(idle=1))


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
            stats("codex", waiting=1), stats("claude", running=2),
        ]), "")
        with patch("ulanzi_tc002.client.agent_berth.subprocess.run", return_value=result):
            main(["watch", "agents", "--once"])
        self.assertEqual(self.updates(), [(name, badge_image(kind, count, name)) for name, kind, count in (
            ("claude", "running", 2), ("codex", "waiting", 1), ("agents", "waiting", 1),
        )])
        calls = self.request.call_args_list
        created = [call.kwargs["json_body"]["name"] for call in calls if call.args[0].endswith("/api/apps")]
        deleted = [call.args[0].rsplit("/", 1)[-1] for call in calls if call.kwargs["method"] == "DELETE"]
        self.assertEqual(created, ["claude", "codex", "agents"])
        self.assertEqual(deleted, ["agents", "codex", "claude"])
        self.assertIn("agents WAITING 1 (waiting=1 running=2 done=0 idle=0)", self.output.getvalue())

    def test_polls_and_updates_changed_counts(self):
        busy = parse_stats([stats(running=1)])
        done = parse_stats([stats(done=1)])
        empty = parse_stats([])
        with patch("ulanzi_tc002.client.agent_berth.read_stats", side_effect=[busy, busy, done, empty, busy]) as read, \
                patch("ulanzi_tc002.client.watch.time.sleep", side_effect=[None] * 4 + [KeyboardInterrupt]) as sleep:
            with self.assertRaises(KeyboardInterrupt):
                main(["watch", "agents", "--interval", "0.25"])
        self.assertEqual(read.call_count, 5)
        self.assertTrue(all(call.args == (0.25,) for call in sleep.call_args_list))
        self.assertEqual(self.updates(), [(name, badge_image(kind, count, name)) for name, kind, count in (
            ("codex", "running", 1), ("agents", "running", 1),
            ("codex", "done", 1), ("agents", "done", 1), ("agents", "idle", 0),
            ("codex", "running", 1), ("agents", "running", 1),
        )])
        deleted = [call.args[0].rsplit("/", 1)[-1] for call in self.request.call_args_list if call.kwargs["method"] == "DELETE"]
        self.assertEqual(deleted, ["codex", "codex", "agents"])
        self.assertIn("No supported agents reported by agent-berth", self.output.getvalue())

    def test_diagnostic_is_printed_only_when_changed(self):
        snapshot = parse_stats([stats("gemini", running=1)])
        with patch("ulanzi_tc002.client.agent_berth.read_stats", side_effect=[snapshot, snapshot]), \
                patch("ulanzi_tc002.client.watch.time.sleep", side_effect=[None, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                main(["watch", "agents"])
        self.assertEqual(self.errors.getvalue().count("Skipping agent-berth provider gemini"), 1)
        self.assertEqual(self.updates(), [("agents", badge_image("idle", 0, "agents"))])

    def test_empty_once_keeps_zero_summary_until_cleanup(self):
        with patch("ulanzi_tc002.client.agent_berth.read_stats", return_value=parse_stats([])):
            main(["watch", "agents", "--once"])
        self.assertEqual(self.updates(), [("agents", badge_image("idle", 0, "agents"))])
        calls = self.request.call_args_list
        self.assertEqual([call.kwargs["method"] for call in calls], ["POST", "POST", "DELETE"])
        self.assertEqual(calls[0].kwargs["json_body"], {"name": "agents", "type": "image"})
        self.assertTrue(calls[-1].args[0].endswith("/api/apps/agents"))

    def test_startup_failure_does_not_create_apps(self):
        with patch("ulanzi_tc002.client.agent_berth.read_stats", side_effect=ValueError("agent-berth not found")):
            with self.assertRaisesRegex(ValueError, "agent-berth not found"):
                main(["watch", "agents", "--once"])
        self.request.assert_not_called()

    def test_read_failure_retries_with_backoff_and_recovers(self):
        busy = parse_stats([stats(running=1)])
        sleeps = []

        def record(delay):
            sleeps.append(delay)
            if len(sleeps) == 4:
                raise KeyboardInterrupt

        with patch("ulanzi_tc002.client.agent_berth.read_stats",
                   side_effect=[busy, ValueError("server unreachable"), ValueError("still down"), busy]) as read, \
                patch("ulanzi_tc002.client.watch.time.sleep", side_effect=record):
            with self.assertRaises(KeyboardInterrupt):
                main(["watch", "agents", "--interval", "1"])
        self.assertEqual(read.call_count, 4)
        self.assertEqual(sleeps, [1, 1, 2, 1])
        errors = self.errors.getvalue()
        self.assertIn("agent-berth: server unreachable; retrying in 1 seconds", errors)
        self.assertIn("agent-berth: still down; retrying in 2 seconds", errors)
        self.assertNotIn("IDLE", self.output.getvalue())
        deleted = [call.args[0].rsplit("/", 1)[-1] for call in self.request.call_args_list
                   if call.kwargs["method"] == "DELETE"]
        self.assertEqual(deleted, ["agents", "codex"])

    def test_retry_backoff_is_capped_at_five_minutes(self):
        sleeps = []

        def record(delay):
            sleeps.append(delay)
            if len(sleeps) == 3:
                raise KeyboardInterrupt

        with patch("ulanzi_tc002.client.agent_berth.read_stats",
                   side_effect=[ValueError("down")] * 3 + [parse_stats([])]), \
                patch("ulanzi_tc002.client.watch.time.sleep", side_effect=record):
            with self.assertRaises(KeyboardInterrupt):
                main(["watch", "agents", "--interval", "100"])
        self.assertEqual(sleeps, [100, 200, 300])
        self.assertIn("agent-berth: down; retrying in 300 seconds", self.errors.getvalue())
        self.request.assert_not_called()

    def test_rejected_badge_cleans_up_created_app(self):
        self.request.return_value = {"accepted": False}
        with patch("ulanzi_tc002.client.agent_berth.read_stats", return_value=parse_stats([stats(running=1)])):
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
                patch("ulanzi_tc002.client.agent_berth.read_stats", return_value=parse_stats([stats(running=1)])), \
                patch("ulanzi_tc002.client.watch.time.sleep", side_effect=stop):
            with self.assertRaises(SystemExit) as error:
                main(["watch", "agents"])
        self.assertEqual(error.exception.code, 0)
        self.assertEqual(handlers[signal.SIGTERM], signal.SIG_DFL)
        self.assertEqual(handlers[signal.SIGINT], signal.SIG_DFL)
        self.assertEqual([call.kwargs["method"] for call in self.request.call_args_list[-2:]], ["DELETE", "DELETE"])

    def test_teardown_deletes_watch_apps_without_polling(self):
        with patch("ulanzi_tc002.client.agent_berth.read_stats") as read:
            main(["watch", "agents", "--teardown"])
        read.assert_not_called()
        calls = self.request.call_args_list
        self.assertTrue(all(call.kwargs["method"] == "DELETE" for call in calls))
        self.assertEqual([call.args[0].rsplit("/", 1)[-1] for call in calls],
                         ["opencode", "claude", "codex", "grok", "pi", "agents"])
        self.assertIn("Deleted agents", self.output.getvalue())

    def test_rejects_invalid_intervals_before_polling(self):
        for interval in ("0", "-1", "nan", "inf"):
            with self.subTest(interval=interval):
                with patch("ulanzi_tc002.client.agent_berth.read_stats") as read:
                    with self.assertRaises(SystemExit) as error:
                        main(["watch", "agents", "--interval", interval])
                    self.assertEqual(error.exception.code, 2)
                    read.assert_not_called()
        self.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
