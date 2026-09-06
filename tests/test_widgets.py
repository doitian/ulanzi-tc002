import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from ulanzi_tc002.client.cli import main
from ulanzi_tc002.device import Device
from ulanzi_tc002.frames import blank_frame, publish, scroll_frames
from ulanzi_tc002.server.apps.text import TextWidget


def write_device_cache(path, ip="192.0.2.10"):
    path.write_text(json.dumps({"ip": ip, "mac": "ccc4b277a363", "network": "192.0.2.0/24"}) + "\n")


class WidgetTests(unittest.TestCase):
    @patch("ulanzi_tc002.client.config.load_client_config", return_value={})
    @patch("ulanzi_tc002.client.cli.request")
    def test_send_uses_server_and_supports_empty_text(self, http_request, _config):
        http_request.return_value = {"accepted": True}
        for message in ["HELLO WORLD", ""]:
            main(["text", "send", "hello", message, "--color", "blue"])
            self.assertEqual(http_request.call_args.args[0], "http://127.0.0.1:8008/api/apps/hello")
            self.assertEqual(http_request.call_args.kwargs["json_body"],
                             {"text": message, "color": "#82AAE8"})
            self.assertEqual(http_request.call_args.kwargs["method"], "POST")

    @patch("ulanzi_tc002.client.config.load_client_config", return_value={})
    @patch("ulanzi_tc002.client.cli.request")
    def test_image_send_and_apps_create_delete(self, http_request, _config):
        http_request.return_value = {"accepted": True, "name": "cat", "deleted": True}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cat.gif"
            path.write_bytes(b"GIF89a" + b"\x00" * 8)
            main(["image", "send", "cat", str(path)])
            self.assertEqual(http_request.call_args.args[0], "http://127.0.0.1:8008/api/apps/cat")
            self.assertTrue(http_request.call_args.kwargs["json_body"]["image"].startswith(
                "data:image/gif;base64,"))
        main(["apps", "create", "image", "cat"])
        self.assertEqual(http_request.call_args.args[0], "http://127.0.0.1:8008/api/apps")
        self.assertEqual(http_request.call_args.kwargs["json_body"], {"name": "cat", "type": "image"})
        main(["apps", "delete", "cat"])
        self.assertEqual(http_request.call_args.args[0], "http://127.0.0.1:8008/api/apps/cat")
        self.assertEqual(http_request.call_args.kwargs["method"], "DELETE")

    def test_marquee_starts_visible_and_repeats_with_half_screen_gap(self):
        from ulanzi_tc002.ansi_text import marquee_offsets
        for message in ["123456789", "HELLO WORLD"]:
            frames = list(scroll_frames(message, "#112233"))
            self.assertEqual(frames[0]["text"][0]["x"], 0)
            self.assertTrue(all(frame["text"] for frame in frames))
            offsets = list(marquee_offsets(len(message) * 6))
            self.assertTrue(all(b - (a + len(message) * 6) == 26 for a, b in offsets))

    def test_api_update_replaces_scroll_and_clear_keeps_app(self):
        device = Mock()
        widget = TextWidget(device, "text", 0.4, publish, scroll_frames)
        widget.update({"text": "HELLO WORLD", "color": "blue"})
        self.assertEqual(device.post.call_args.args[2]["text"][0]["x"], 0)
        self.assertEqual(widget.state[1], "#82AAE8")
        widget.update({"text": "HI"})
        self.assertEqual(device.post.call_args.args[2]["text"][0]["align"], "center")
        self.assertEqual(widget.state[1], "#FFFFFF")
        widget.update({"text": ""})
        self.assertEqual(device.post.call_args.args[2], blank_frame())
        self.assertEqual(list(widget.cycle()), [blank_frame()])
        self.assertEqual(device.post.call_args.args[1], "text")

    def test_invalid_updates_leave_message_unchanged(self):
        device = Mock()
        widget = TextWidget(device, "text", 0.4, publish, scroll_frames)
        widget.update({"text": "HI"})
        for payload in [{}, {"text": 4}, {"text": "OK", "color": "bad"},
                        {"text": "X" * 257}, {"text": "non-ascii \u2603"}]:
            with self.assertRaises(ValueError):
                widget.update(payload)
        self.assertEqual(widget.state, ("HI", "#FFFFFF"))
        self.assertEqual(device.post.call_count, 1)

    def test_fitting_text_stays_centered(self):
        for message in ["HI", "12345678"]:
            frames = list(scroll_frames(message, "white"))
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0]["text"][0]["align"], "center")
            self.assertEqual(frames[0]["text"][0]["x"], -1000)

    @patch("ulanzi_tc002.device.discover")
    def test_success_uses_cache_without_lookup(self, discover):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "device.json"
            write_device_cache(cache)
            client = Device(cache=cache)
            client.post(Mock(return_value={"code": 200}), "info", {})
            discover.assert_not_called()
            self.assertEqual(Device(cache=cache).address, "192.0.2.10")

    @patch("ulanzi_tc002.device.discover", return_value="192.0.2.11")
    def test_missing_cache_scans_on_first_post(self, discover):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "device.json"
            client = Device(cache=cache)
            self.assertIsNone(client.address)
            client.post(Mock(return_value={"code": 200}), "info", {})
            discover.assert_called_once()
            self.assertEqual(Device(cache=cache).address, "192.0.2.11")

    @patch("ulanzi_tc002.device.discover", return_value="192.0.2.11")
    def test_network_failure_discovers_retries_and_persists(self, discover):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "device.json"
            write_device_cache(cache)
            client = Device(cache=cache)
            sender = Mock(side_effect=[URLError("timed out"), {"code": 200}])
            client.post(sender, "info", {})
            self.assertEqual(sender.call_args_list[1].args[0], "192.0.2.11")
            self.assertEqual(Device(cache=cache).address, "192.0.2.11")
            discover.assert_called_once()

    @patch("ulanzi_tc002.device.discover")
    def test_http_error_does_not_discover(self, discover):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "device.json"
            write_device_cache(cache)
            client = Device(cache=cache)
            sender = Mock(side_effect=HTTPError("http://clock", 500, "error", {}, None))
            with self.assertRaises(HTTPError):
                client.post(sender, "info", {})
            discover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
