import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from ulanzi_tc002.client.badge import BLACK, HEIGHT, OPENCODE_OUTER, PI_OUTER, WIDTH, compose
from ulanzi_tc002.client.bridge import Bridge, BridgeStore
from ulanzi_tc002.client.cli import main
from ulanzi_tc002.client.pi import (
    extension_path,
    extension_source,
    install_extension,
    remove_extension,
)
from ulanzi_tc002.client.watch import parse_providers


class PiBridgeTests(unittest.TestCase):
    def test_post_aggregates_and_stale_drops(self):
        store = BridgeStore(stale=5)
        store.update("pi", {
            "id": "1",
            "status": {"s1": "busy", "s2": "idle"},
            "blocking": ["s1"],
        })
        store.update("pi", {
            "id": "2",
            "status": {"s3": "busy"},
            "blocking": [],
        })
        kind, count, counts = store.snapshot("pi")
        self.assertEqual((kind, count), ("ask", 1))
        self.assertEqual(counts, {"ask": 1, "run": 1, "idle": 1})
        kind, count, counts = store.snapshot("pi", now=store.instances[("pi", "1")]["updated"] + 6)
        self.assertEqual((kind, count), ("idle", 0))

    def test_http_post(self):
        store = BridgeStore()
        bridge = Bridge("127.0.0.1", 0, store, {"pi"})
        bridge.start()
        try:
            request = Request(
                bridge.url + "/providers/pi",
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
            kind, count, counts = store.snapshot("pi")
            self.assertEqual((kind, count), ("ask", 1))
            self.assertEqual(counts["ask"], 1)
        finally:
            bridge.stop()


class PiBadgeTests(unittest.TestCase):
    def test_logo_uses_pi_color(self):
        pixels = compose("idle", 0, "pi")
        self.assertEqual(len(pixels), HEIGHT)
        self.assertTrue(all(len(row) == WIDTH for row in pixels))
        colors = {pixel for row in pixels for pixel in row}
        self.assertIn(PI_OUTER, colors)
        self.assertNotIn(OPENCODE_OUTER, colors)
        self.assertIn(BLACK, colors)

    def test_provider_logos_share_center(self):
        def center(pixels, color):
            xs = [x for row in pixels for x, pixel in enumerate(row) if pixel == color]
            ys = [y for y, row in enumerate(pixels) for pixel in row if pixel == color]
            return (min(xs) + max(xs), min(ys) + max(ys))
        opencode = compose("idle", 0, "opencode")
        pi = compose("idle", 0, "pi")
        self.assertEqual(center(opencode, OPENCODE_OUTER), center(pi, PI_OUTER))


class PiCliTests(unittest.TestCase):
    def test_parse_providers_includes_pi(self):
        self.assertEqual(parse_providers("pi"), ["pi"])
        self.assertEqual(
            parse_providers("opencode,claude,codex,grok,pi"),
            ["opencode", "claude", "codex", "grok", "pi"],
        )

    def test_install_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = {"PI_CODING_AGENT_DIR": tmp}
            dest = install_extension("http://127.0.0.1:8010", environ)
            self.assertEqual(dest, extension_path(environ))
            self.assertTrue(dest.exists())
            source = dest.read_text(encoding="utf-8")
            self.assertIn("http://127.0.0.1:8010", source)
            self.assertIn("/providers/pi", source)
            self.assertNotIn("http://127.0.0.1:8009", source)
            remove_extension(environ)
            self.assertFalse(dest.exists())

    def test_extension_source_rewrites_bridge_url(self):
        source = extension_source("http://127.0.0.1:8010")
        self.assertIn("http://127.0.0.1:8010", source)
        self.assertNotIn("http://127.0.0.1:8009", source)

    @patch("ulanzi_tc002.client.config.load_client_config", return_value={})
    @patch("ulanzi_tc002.client.cli.request")
    def test_once_installs_extension_creates_app_and_cleans_up(self, cli_request, _config):
        cli_request.return_value = {"accepted": True, "name": "pi", "deleted": True}
        with tempfile.TemporaryDirectory() as tmp:
            environ = {**os.environ, "PI_CODING_AGENT_DIR": tmp}
            stdout = io.StringIO()
            with patch.dict(os.environ, environ, clear=True), patch("sys.stdout", stdout):
                main(["watch", "agents", "--providers", "pi", "--once", "--bridge-port", "0"])
                self.assertFalse(extension_path(environ).exists())
            methods = [call.kwargs["method"] for call in cli_request.call_args_list]
            bodies = [call.kwargs.get("json_body") for call in cli_request.call_args_list]
            paths = [call.args[0] for call in cli_request.call_args_list]
            self.assertEqual(methods[0], "POST")
            self.assertEqual(bodies[0], {"name": "pi", "type": "image"})
            self.assertTrue(paths[0].endswith("/api/apps"))
            self.assertEqual(methods[1], "POST")
            self.assertTrue(paths[1].endswith("/api/apps/pi"))
            self.assertTrue(bodies[1]["image"].startswith("data:image/png;base64,"))
            self.assertEqual(methods[-1], "DELETE")
            self.assertTrue(paths[-1].endswith("/api/apps/pi"))
            self.assertIn("pi IDLE", stdout.getvalue())
            self.assertNotIn("IDLE 0", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
