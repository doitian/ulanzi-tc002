import io
import json
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ulanzi_tc002.client.badge import BLACK, HEIGHT, OPENCODE_OUTER, STATUS_COLOR, WIDTH, badge_image, compose, png_bytes
from ulanzi_tc002.client.bridge import Bridge, BridgeStore
from ulanzi_tc002.client.claude import install_hooks as install_claude_hooks, settings_path
from ulanzi_tc002.client.cli import main
from ulanzi_tc002.client.codex import hooks_path as codex_hooks_path, install_hooks as install_codex_hooks, script_path as codex_script_path
from ulanzi_tc002.client.grok import hooks_path as grok_hooks_path, install_hooks as install_grok_hooks, script_path as grok_script_path
from ulanzi_tc002.client.opencode import install_plugin, plugin_path, plugin_source, summarize
from ulanzi_tc002.client.watch import parse_providers


class SummarizeTests(unittest.TestCase):
    def test_ask_beats_run_and_idle(self):
        kind, count, counts = summarize(
            {"a": "busy", "b": "idle", "c": "retry"},
            {"a", "d"},
        )
        self.assertEqual((kind, count), ("ask", 2))
        self.assertEqual(counts, {"ask": 2, "run": 1, "idle": 1})

    def test_run_includes_retry_when_nothing_blocks(self):
        kind, count, counts = summarize({"a": "busy", "b": "retry", "c": "idle"}, set())
        self.assertEqual((kind, count), ("run", 2))
        self.assertEqual(counts, {"ask": 0, "run": 2, "idle": 1})

    def test_idle_after_run_when_nothing_else_is_active(self):
        kind, count, counts = summarize({"a": "idle", "b": "idle"}, set())
        self.assertEqual((kind, count), ("idle", 2))
        self.assertEqual(counts, {"ask": 0, "run": 0, "idle": 2})

    def test_idle_zero_when_empty(self):
        kind, count, counts = summarize({}, set())
        self.assertEqual((kind, count), ("idle", 0))
        self.assertEqual(counts, {"ask": 0, "run": 0, "idle": 0})

    def test_same_session_permission_and_question_count_once(self):
        kind, count, counts = summarize({"a": "busy"}, {"a"})
        self.assertEqual((kind, count), ("ask", 1))
        self.assertEqual(counts, {"ask": 1, "run": 0, "idle": 0})


class BadgeTests(unittest.TestCase):
    def test_canvas_size_and_status_color(self):
        pixels = compose("ask", 2)
        self.assertEqual(len(pixels), HEIGHT)
        self.assertTrue(all(len(row) == WIDTH for row in pixels))
        self.assertIn(STATUS_COLOR["ask"], {pixel for row in pixels for pixel in row})
        self.assertNotIn(STATUS_COLOR["run"], {pixel for row in pixels for pixel in row})
        idle = {pixel for row in compose("idle", 0) for pixel in row}
        self.assertIn(STATUS_COLOR["idle"], idle)
        self.assertIn(BLACK, idle)
        self.assertTrue(png_bytes(pixels).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(badge_image("ask", 2).startswith("data:image/png;base64,"))

    def test_count_caps_at_nine_plus(self):
        self.assertNotEqual(compose("ask", 9), compose("ask", 10))
        self.assertEqual(compose("ask", 10), compose("ask", 11))

    def test_icons_stay_put_when_count_changes(self):
        def logo(pixels):
            return tuple(
                (x, y)
                for y, row in enumerate(pixels)
                for x, pixel in enumerate(row)
                if pixel == OPENCODE_OUTER
            )
        none = logo(compose("ask", 0))
        self.assertEqual(none, logo(compose("ask", 1)))
        self.assertEqual(none, logo(compose("ask", 12)))

    def test_status_is_vertically_centered(self):
        for kind, color in STATUS_COLOR.items():
            rows = [y for y, row in enumerate(compose(kind, 0)) if color in row]
            self.assertLessEqual(abs(rows[0] - (HEIGHT - 1 - rows[-1])), 1, kind)

    def test_agents_logo_is_not_a_provider_logo(self):
        agents = compose("idle", 0, "agents")
        for name in ("opencode", "claude", "codex", "grok"):
            self.assertNotEqual(agents, compose("idle", 0, name), name)


class BridgeTests(unittest.TestCase):
    def test_post_aggregates_and_stale_drops(self):
        store = BridgeStore(stale=5)
        store.update("opencode", {
            "id": "1",
            "status": {"s1": "busy", "s2": "idle"},
            "blocking": ["s1"],
        })
        store.update("opencode", {
            "id": "2",
            "status": {"s3": "retry"},
            "blocking": [],
        })
        kind, count, counts = store.snapshot("opencode")
        self.assertEqual((kind, count), ("ask", 1))
        self.assertEqual(counts, {"ask": 1, "run": 1, "idle": 1})
        kind, count, counts = store.snapshot("opencode", now=store.instances[("opencode", "1")]["updated"] + 6)
        self.assertEqual((kind, count), ("idle", 0))

    def test_http_post_and_health(self):
        store = BridgeStore()
        bridge = Bridge("127.0.0.1", 0, store, {"opencode"})
        bridge.start()
        try:
            health = json.loads(urlopen(bridge.url + "/health", timeout=2).read())
            self.assertEqual(health, {"ok": True})
            request = Request(
                bridge.url + "/providers/opencode",
                data=json.dumps({
                    "id": "p1",
                    "status": {"s1": "busy"},
                    "blocking": ["s1"],
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 204)
            kind, count, counts = store.snapshot("opencode")
            self.assertEqual((kind, count), ("ask", 1))
            self.assertEqual(counts["ask"], 1)
            with self.assertRaises(HTTPError) as raised:
                urlopen(Request(bridge.url + "/providers/nope", data=b"{}", method="POST"), timeout=2)
            self.assertEqual(raised.exception.code, 404)
        finally:
            bridge.stop()


class WatchCliTests(unittest.TestCase):
    def test_parse_providers(self):
        self.assertEqual(parse_providers("opencode,opencode"), ["opencode"])
        self.assertEqual(parse_providers("claude"), ["claude"])
        self.assertEqual(parse_providers("opencode,claude"), ["opencode", "claude"])
        self.assertEqual(parse_providers("codex"), ["codex"])
        self.assertEqual(parse_providers("grok"), ["grok"])
        with self.assertRaises(ValueError):
            parse_providers("nope")

    @patch("ulanzi_tc002.client.config.load_client_config", return_value={})
    @patch("ulanzi_tc002.client.cli.request")
    def test_once_installs_plugin_creates_app_and_cleans_up(self, cli_request, _config):
        cli_request.return_value = {"accepted": True, "name": "opencode", "deleted": True}
        with tempfile.TemporaryDirectory() as tmp:
            environ = {**os.environ, "XDG_CONFIG_HOME": tmp}
            stdout = io.StringIO()
            with patch.dict(os.environ, environ, clear=True), patch("sys.stdout", stdout):
                main(["watch", "agents", "--providers", "opencode", "--once", "--bridge-port", "0"])
                self.assertFalse(plugin_path(environ).exists())
            methods = [call.kwargs["method"] for call in cli_request.call_args_list]
            bodies = [call.kwargs.get("json_body") for call in cli_request.call_args_list]
            paths = [call.args[0] for call in cli_request.call_args_list]
            self.assertEqual(methods[0], "POST")
            self.assertEqual(bodies[0], {"name": "opencode", "type": "image"})
            self.assertTrue(paths[0].endswith("/api/apps"))
            self.assertEqual(methods[1], "POST")
            self.assertTrue(paths[1].endswith("/api/apps/opencode"))
            self.assertTrue(bodies[1]["image"].startswith("data:image/png;base64,"))
            self.assertEqual(methods[-1], "DELETE")
            self.assertTrue(paths[-1].endswith("/api/apps/opencode"))
            self.assertIn("opencode IDLE", stdout.getvalue())
            self.assertNotIn("IDLE 0", stdout.getvalue())

    @patch("ulanzi_tc002.client.config.load_client_config", return_value={})
    @patch("ulanzi_tc002.client.cli.request")
    def test_existing_app_and_plugin_still_cleaned(self, cli_request, _config):
        cli_request.side_effect = [
            ValueError("App already exists"),
            {"accepted": True},
            {"deleted": True},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            environ = {**os.environ, "XDG_CONFIG_HOME": tmp}
            stdout = io.StringIO()
            with patch.dict(os.environ, environ, clear=True), patch("sys.stdout", stdout):
                main(["watch", "agents", "--providers", "opencode", "--once", "--bridge-port", "0"])
                self.assertFalse(plugin_path(environ).exists())
            self.assertEqual(cli_request.call_args_list[-1].kwargs["method"], "DELETE")
            self.assertIn("opencode IDLE", stdout.getvalue())
            self.assertNotIn("IDLE 0", stdout.getvalue())

    def test_plugin_source_rewrites_bridge_url(self):
        source = plugin_source("http://127.0.0.1:8010")
        self.assertIn("http://127.0.0.1:8010", source)
        self.assertNotIn("http://127.0.0.1:8009", source)

    @patch("ulanzi_tc002.client.config.load_client_config", return_value={})
    def test_starts_without_providers(self, _config):
        with patch("ulanzi_tc002.client.watch.watch_agents") as watch:
            main(["watch", "agents"])
        self.assertEqual(watch.call_args.args[0].providers, [])

    @patch("ulanzi_tc002.client.cli.request")
    def test_teardown_removes_all_provider_configs(self, cli_request):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environ = {
                **os.environ,
                "XDG_CONFIG_HOME": str(root / "xdg"),
                "CLAUDE_CONFIG_DIR": str(root / "claude"),
                "CODEX_HOME": str(root / "codex"),
                "GROK_HOME": str(root / "grok"),
            }
            install_plugin("http://127.0.0.1:8009", environ)
            install_claude_hooks("http://127.0.0.1:8009", environ)
            install_codex_hooks("http://127.0.0.1:8009", environ)
            install_grok_hooks("http://127.0.0.1:8009", environ)
            self.assertTrue(plugin_path(environ).exists())
            self.assertTrue(settings_path(environ).exists())
            self.assertTrue(codex_hooks_path(environ).exists())
            self.assertTrue(codex_script_path(environ).exists())
            self.assertTrue(grok_hooks_path(environ).exists())
            self.assertTrue(grok_script_path(environ).exists())
            with patch.dict(os.environ, environ, clear=True):
                main(["watch", "agents", "--teardown"])
            self.assertFalse(plugin_path(environ).exists())
            self.assertFalse(settings_path(environ).exists())
            self.assertFalse(codex_hooks_path(environ).exists())
            self.assertFalse(codex_script_path(environ).exists())
            self.assertFalse(grok_hooks_path(environ).exists())
            self.assertFalse(grok_script_path(environ).exists())
            self.assertFalse(cli_request.called)

    @patch("ulanzi_tc002.client.cli.request")
    def test_teardown_respects_providers(self, cli_request):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environ = {
                **os.environ,
                "XDG_CONFIG_HOME": str(root / "xdg"),
                "CLAUDE_CONFIG_DIR": str(root / "claude"),
            }
            install_plugin("http://127.0.0.1:8009", environ)
            install_claude_hooks("http://127.0.0.1:8009", environ)
            with patch.dict(os.environ, environ, clear=True):
                main(["watch", "agents", "--providers", "claude", "--teardown"])
            self.assertTrue(plugin_path(environ).exists())
            self.assertFalse(settings_path(environ).exists())
            self.assertFalse(cli_request.called)

    @patch("ulanzi_tc002.client.config.load_client_config", return_value={})
    @patch("ulanzi_tc002.client.cli.request")
    def test_sigterm_tears_down_plugin(self, cli_request, _config):
        cli_request.return_value = {"accepted": True, "name": "opencode", "deleted": True}
        handlers = {}

        def bind(sig, handler):
            handlers[sig] = handler
            return signal.SIG_DFL

        def trip(timeout):
            handlers[signal.SIGTERM](signal.SIGTERM, None)

        with tempfile.TemporaryDirectory() as tmp:
            environ = {**os.environ, "XDG_CONFIG_HOME": tmp}
            with patch.dict(os.environ, environ, clear=True):
                with patch("ulanzi_tc002.client.watch.signal.signal", bind):
                    with patch("ulanzi_tc002.client.watch.queue.Queue.get", side_effect=trip), patch("sys.stdin", io.StringIO()):
                        with self.assertRaises(SystemExit) as ctx:
                            main(["watch", "agents", "--providers", "opencode", "--bridge-port", "0"])
            self.assertEqual(ctx.exception.code, 0)
            self.assertFalse(plugin_path(environ).exists())
            self.assertEqual(cli_request.call_args_list[-1].kwargs["method"], "DELETE")


if __name__ == "__main__":
    unittest.main()
