import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ulanzi_tc002.client.badge import BLACK, HEIGHT, OPENCODE_OUTER, STATUS_COLOR, WIDTH, badge_image, compose, png_bytes
from ulanzi_tc002.client.bridge import Bridge, BridgeStore
from ulanzi_tc002.client.cli import main
from ulanzi_tc002.client.opencode import plugin_path, plugin_source, summarize
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


if __name__ == "__main__":
    unittest.main()
