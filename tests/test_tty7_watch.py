import io
import json
import signal
import subprocess
import unittest
from unittest.mock import patch

from ulanzi_tc002.client.badge import badge_image
from ulanzi_tc002.client.cli import main
from ulanzi_tc002.client.tty7 import parse_status, read_status


def pane(pane_id, status, agent="Codex", session_id="session"):
    return {
        "pane_id": pane_id, "agent": agent,
        "state": {"status": status, "session_id": session_id, "message": None},
    }


class Tty7StatusTests(unittest.TestCase):
    def test_uses_nested_state_and_groups_panes_by_agent(self):
        states, diagnostics = parse_status({"agents": [
            pane(1, "waiting"), pane(2, "working", "Claude"),
            pane(3, "done", "Codex"), pane(4, "idle", "OpenCode"),
            pane(5, "working", "Grok"), pane(6, "waiting", "Pi"),
        ]})
        self.assertEqual(states, [
            ("opencode", "idle", 1, {"ask": 0, "run": 0, "idle": 1}),
            ("claude", "run", 1, {"ask": 0, "run": 1, "idle": 0}),
            ("codex", "ask", 1, {"ask": 1, "run": 0, "idle": 1}),
            ("grok", "run", 1, {"ask": 0, "run": 1, "idle": 0}),
            ("pi", "ask", 1, {"ask": 1, "run": 0, "idle": 0}),
        ])
        self.assertEqual(diagnostics, ())

    def test_same_pane_is_counted_once(self):
        states, _ = parse_status({"agents": [pane(1, "working"), pane(1, "done")]})
        self.assertEqual(states, [("codex", "idle", 1, {"ask": 0, "run": 0, "idle": 1})])

    def test_empty_agents_has_no_provider_apps(self):
        self.assertEqual(parse_status({"agents": []})[0], [])

    def test_unmapped_agents_are_reported_and_do_not_create_apps(self):
        states, diagnostics = parse_status({"agents": [
            pane(1, "working", "Gemini"), pane(2, "idle", None), pane(3, "working", "Gemini"),
        ]})
        self.assertEqual(states, [])
        self.assertEqual(len(diagnostics), 2)
        self.assertIn("gemini", diagnostics[0])

    def test_malformed_responses_are_not_reported_as_idle(self):
        for payload in (None, [], {}, {"agents": {}}, {"agents": [None]},
                        {"agents": [{"pane_id": 1, "status": "working"}]},
                        {"agents": [pane(True, "working")]},
                        {"agents": [pane(-1, "working")]},
                        {"agents": [pane(1, "unknown")]},
                        {"agents": [], "diagnostics": {}},
                        {"agents": [], "diagnostics": [None]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_status(payload)

    def test_missing_hook_diagnostics_are_preserved_without_counting_agents(self):
        states, diagnostics = parse_status({"agents": [], "diagnostics": [{
            "kind": "agent_status_hooks_unavailable", "agent": "codex",
            "hooks_state": "not_installed", "action": "install",
        }]})
        self.assertEqual(states, [])
        self.assertIn("codex", diagnostics[0])
        self.assertIn("not installed", diagnostics[0])
        self.assertIn("install them in tty7 Settings > Agents", diagnostics[0])

    def test_reads_local_and_linked_machine_without_a_shell(self):
        for machine in (None, "devbox"):
            with self.subTest(machine=machine):
                result = subprocess.CompletedProcess([], 0, json.dumps({"agents": [pane(1, "working")]}), "")
                with patch("ulanzi_tc002.client.tty7.subprocess.run", return_value=result) as run:
                    self.assertEqual(read_status(machine)[0][0][:3], ("codex", "run", 1))
                expected = ["tty7", "agents", "--json"]
                if machine:
                    expected += ["--machine", machine]
                self.assertEqual(run.call_args.args, (expected,))
                self.assertEqual(run.call_args.kwargs["timeout"], 5)
                self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
                self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_command_errors_are_actionable(self):
        for error, message in ((FileNotFoundError(), "not found on PATH"),
                               (subprocess.TimeoutExpired("tty7", 5), "timed out")):
            with self.subTest(error=error):
                with patch("ulanzi_tc002.client.tty7.subprocess.run", side_effect=error):
                    with self.assertRaisesRegex(ValueError, message):
                        read_status()
        for code, stdout, stderr, message in (
            (1, "", "server unreachable", "server unreachable"),
            (1, "", "", "exit code 1"),
            (0, "not json", "", "Invalid JSON"),
            (0, "{}", "", "expected an agents array"),
        ):
            with self.subTest(code=code, stdout=stdout, stderr=stderr):
                result = subprocess.CompletedProcess([], code, stdout, stderr)
                with patch("ulanzi_tc002.client.tty7.subprocess.run", return_value=result):
                    with self.assertRaisesRegex(ValueError, message):
                        read_status()


class Tty7WatchTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("ulanzi_tc002.client.config.load_client_config", return_value={}))
        self.output = self.enterContext(patch("sys.stdout", new_callable=io.StringIO))
        self.errors = self.enterContext(patch("sys.stderr", new_callable=io.StringIO))
        self.request = self.enterContext(patch("ulanzi_tc002.client.cli.request", return_value={"accepted": True}))

    def test_once_creates_provider_and_summary_badges_without_installing_hooks(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({"agents": [pane(1, "waiting")]}), "")
        with patch("ulanzi_tc002.client.tty7.subprocess.run", return_value=result), \
                patch("ulanzi_tc002.client.watch.Bridge") as bridge, \
                patch("ulanzi_tc002.client.watch.WatchProviders") as providers:
            main(["watch", "tty7", "--once"])
        bridge.assert_not_called()
        providers.assert_not_called()
        calls = self.request.call_args_list
        self.assertEqual([call.kwargs["method"] for call in calls], ["POST"] * 4 + ["DELETE"] * 2)
        self.assertEqual(calls[0].kwargs["json_body"], {"name": "codex", "type": "image"})
        self.assertTrue(calls[1].args[0].endswith("/api/apps/codex"))
        self.assertEqual(calls[1].kwargs["json_body"], {"image": badge_image("ask", 1, "codex")})
        self.assertEqual(calls[2].kwargs["json_body"], {"name": "agents", "type": "image"})
        self.assertTrue(calls[3].args[0].endswith("/api/apps/agents"))
        self.assertEqual(calls[3].kwargs["json_body"], {"image": badge_image("ask", 1, "agents")})
        self.assertTrue(calls[-2].args[0].endswith("/api/apps/agents"))
        self.assertTrue(calls[-1].args[0].endswith("/api/apps/codex"))
        self.assertIn("codex ASK 1 (ask=1 run=0 idle=0)", self.output.getvalue())
        self.assertIn("agents ASK 1 (ask=1 run=0 idle=0)", self.output.getvalue())

    def test_summary_counts_panes_across_providers(self):
        snapshot = parse_status({"agents": [
            pane(1, "working"), pane(2, "working"), pane(3, "working", "Claude"),
        ]})
        with patch("ulanzi_tc002.client.tty7.read_status", return_value=snapshot):
            main(["watch", "tty7", "--once"])
        updates = [call.kwargs["json_body"] for call in self.request.call_args_list
                   if call.kwargs["method"] == "POST" and call.args[0].endswith("/api/apps/agents")]
        self.assertEqual(updates, [{"image": badge_image("run", 3, "agents")}])
        self.assertIn("agents RUN 3 (ask=0 run=3 idle=0)", self.output.getvalue())

    def test_polls_without_stdin_and_sends_only_changed_counts(self):
        busy = parse_status({"agents": [pane(1, "working")]})
        done = parse_status({"agents": [pane(1, "done")]})
        empty = parse_status({"agents": []})
        with patch("sys.stdin", io.StringIO()), \
                patch("ulanzi_tc002.client.tty7.read_status", side_effect=[busy, busy, done, empty]) as read, \
                patch("ulanzi_tc002.client.tty7.time.sleep", side_effect=[None, None, None, KeyboardInterrupt]) as sleep:
            with self.assertRaises(KeyboardInterrupt):
                main(["watch", "tty7", "--machine", "devbox", "--interval", "0.25"])
        self.assertEqual(read.call_count, 4)
        self.assertTrue(all(call.args == ("devbox",) for call in read.call_args_list))
        self.assertTrue(all(call.args == (0.25,) for call in sleep.call_args_list))
        updates = [call for call in self.request.call_args_list
                   if call.kwargs["method"] == "POST" and "/api/apps/" in call.args[0]]
        self.assertEqual(
            [(call.args[0].rsplit("/", 1)[-1], call.kwargs["json_body"]["image"]) for call in updates],
            [(name, badge_image(kind, count, name)) for name, kind, count in (
                ("codex", "run", 1), ("agents", "run", 1),
                ("codex", "idle", 1), ("agents", "idle", 1), ("agents", "idle", 0),
            )],
        )
        self.assertEqual(self.request.call_args_list[-1].kwargs["method"], "DELETE")
        self.assertIn("codex IDLE 1", self.output.getvalue())
        self.assertIn("No supported agents reported by tty7", self.output.getvalue())

    def test_summary_persists_as_provider_apps_appear_and_disappear(self):
        codex = parse_status({"agents": [pane(1, "working")]})
        both = parse_status({"agents": [pane(1, "working"), pane(2, "waiting", "Claude")]})
        claude = parse_status({"agents": [pane(2, "done", "Claude")]})
        empty = parse_status({"agents": []})
        with patch("ulanzi_tc002.client.tty7.read_status", side_effect=[codex, both, claude, empty, codex]), \
                patch("ulanzi_tc002.client.tty7.time.sleep", side_effect=[None] * 4 + [KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                main(["watch", "tty7"])
        created = [call.kwargs["json_body"]["name"] for call in self.request.call_args_list
                   if call.args[0].endswith("/api/apps")]
        deleted = [call.args[0].rsplit("/", 1)[-1] for call in self.request.call_args_list
                   if call.kwargs["method"] == "DELETE"]
        self.assertEqual(created, ["codex", "agents", "claude", "codex"])
        self.assertEqual(deleted, ["codex", "claude", "codex", "agents"])
        self.assertIn("agents ASK 1 (ask=1 run=1 idle=0)", self.output.getvalue())

    def test_empty_once_sends_zero_total_and_cleans_up(self):
        with patch("ulanzi_tc002.client.tty7.read_status", return_value=parse_status({"agents": []})):
            main(["watch", "tty7", "--once"])
        calls = self.request.call_args_list
        self.assertEqual([call.kwargs["method"] for call in calls], ["POST", "POST", "DELETE"])
        self.assertEqual(calls[0].kwargs["json_body"], {"name": "agents", "type": "image"})
        self.assertTrue(calls[1].args[0].endswith("/api/apps/agents"))
        self.assertEqual(calls[1].kwargs["json_body"], {"image": badge_image("idle", 0, "agents")})
        self.assertTrue(calls[2].args[0].endswith("/api/apps/agents"))
        self.assertIn("agents IDLE (ask=0 run=0 idle=0)", self.output.getvalue())
        self.assertIn("No supported agents reported by tty7", self.output.getvalue())

    def test_diagnostics_are_printed_only_when_changed(self):
        snapshot = ([], ("codex: install hooks",))
        with patch("ulanzi_tc002.client.tty7.read_status", side_effect=[snapshot, snapshot]), \
                patch("ulanzi_tc002.client.tty7.time.sleep", side_effect=[None, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                main(["watch", "tty7"])
        self.assertEqual(self.errors.getvalue().count("codex: install hooks"), 1)

    def test_startup_failure_does_not_create_a_display(self):
        with patch("ulanzi_tc002.client.tty7.read_status", side_effect=ValueError("server unreachable")):
            with self.assertRaisesRegex(ValueError, "server unreachable"):
                main(["watch", "tty7", "--once"])
        self.request.assert_not_called()

    def test_connection_loss_cleans_up_instead_of_reporting_idle(self):
        busy = parse_status({"agents": [pane(1, "working")]})
        with patch("ulanzi_tc002.client.tty7.read_status", side_effect=[busy, ValueError("server unreachable")]), \
                patch("ulanzi_tc002.client.tty7.time.sleep"):
            with self.assertRaisesRegex(ValueError, "server unreachable"):
                main(["watch", "tty7"])
        self.assertEqual(self.request.call_args_list[-1].kwargs["method"], "DELETE")
        self.assertNotIn("IDLE", self.output.getvalue())

    def test_sigterm_cleans_up_and_restores_handlers(self):
        handlers = {}

        def bind(sig, handler):
            handlers[sig] = handler
            return signal.SIG_DFL

        def stop(_interval):
            handlers[signal.SIGTERM](signal.SIGTERM, None)

        with patch("ulanzi_tc002.client.watch.signal.signal", side_effect=bind), \
                patch("ulanzi_tc002.client.tty7.read_status", return_value=parse_status({"agents": [pane(1, "working")]})), \
                patch("ulanzi_tc002.client.tty7.time.sleep", side_effect=stop):
            with self.assertRaises(SystemExit) as error:
                main(["watch", "tty7"])
        self.assertEqual(error.exception.code, 0)
        self.assertEqual(handlers[signal.SIGTERM], signal.SIG_DFL)
        self.assertEqual(handlers[signal.SIGINT], signal.SIG_DFL)
        self.assertEqual(self.request.call_args_list[-1].kwargs["method"], "DELETE")

    def test_rejects_invalid_intervals_before_polling(self):
        for interval in ("0", "-1", "nan", "inf"):
            with self.subTest(interval=interval):
                with patch("ulanzi_tc002.client.tty7.read_status") as read:
                    with self.assertRaises(SystemExit) as error:
                        main(["watch", "tty7", "--interval", interval])
                    self.assertEqual(error.exception.code, 2)
                    read.assert_not_called()
        self.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
