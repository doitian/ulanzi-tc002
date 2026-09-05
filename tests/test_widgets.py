import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from device import Device
import tc002


class WidgetTests(unittest.TestCase):
    @patch("tc002.urllib.request.build_opener")
    @patch("tc002.Device")
    def test_send_uses_server_and_supports_empty_text(self, device, build_opener):
        response = build_opener.return_value.open.return_value.__enter__.return_value
        response.read.return_value = b'{"accepted": true}'
        for message in ["HELLO WORLD", ""]:
            tc002.main(["text", "send", message, "--color", "blue"])
            request = build_opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "http://127.0.0.1:8008/text")
            self.assertEqual(json.loads(request.data), {"text": message, "color": "#82AAE8"})
        device.assert_not_called()

    def test_marquee_starts_visible_and_repeats_with_half_screen_gap(self):
        from ansi_text import marquee_offsets
        for message in ["123456789", "HELLO WORLD"]:
            frames = list(tc002.scroll_frames(message, "#112233"))
            self.assertEqual(frames[0]["text"][0]["x"], 0)
            self.assertTrue(all(frame["text"] for frame in frames))
            offsets = list(marquee_offsets(len(message) * 6))
            self.assertTrue(all(b - (a + len(message) * 6) == 26 for a, b in offsets))

    def test_api_update_replaces_scroll_and_clear_keeps_app(self):
        from text_server import TextWidget, blank_frame
        device = Mock()
        widget = TextWidget(device, "text", 0.4, tc002.publish, tc002.scroll_frames)
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
        from text_server import TextWidget
        device = Mock()
        widget = TextWidget(device, "text", 0.4, tc002.publish, tc002.scroll_frames)
        widget.update({"text": "HI"})
        for payload in [{}, {"text": 4}, {"text": "OK", "color": "bad"},
                        {"text": "X" * 257}, {"text": "non-ascii \u2603"}]:
            with self.assertRaises(ValueError):
                widget.update(payload)
        self.assertEqual(widget.state, ("HI", "#FFFFFF"))
        self.assertEqual(device.post.call_count, 1)

    def test_fitting_text_stays_centered(self):
        for message in ["HI", "12345678"]:
            frames = list(tc002.scroll_frames(message, "white"))
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0]["text"][0]["align"], "center")
            self.assertEqual(frames[0]["text"][0]["x"], -1000)

    @patch("device.discover")
    def test_success_uses_cache_without_lookup(self, discover):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "device.json"
            client = Device(cache=cache)
            client.post(Mock(return_value={"code": 200}), "info", {})
            discover.assert_not_called()
            self.assertEqual(Device(cache=cache).address, "10.31.3.197")

    @patch("device.discover", return_value="10.31.3.198")
    def test_network_failure_discovers_retries_and_persists(self, discover):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "device.json"
            client = Device(cache=cache)
            sender = Mock(side_effect=[URLError("timed out"), {"code": 200}])
            client.post(sender, "info", {})
            self.assertEqual(sender.call_args_list[1].args[0], "10.31.3.198")
            self.assertEqual(Device(cache=cache).address, "10.31.3.198")
            discover.assert_called_once()

    @patch("device.discover")
    def test_http_error_does_not_discover(self, discover):
        with tempfile.TemporaryDirectory() as directory:
            client = Device(cache=Path(directory) / "device.json")
            sender = Mock(side_effect=HTTPError("http://clock", 500, "error", {}, None))
            with self.assertRaises(HTTPError):
                client.post(sender, "info", {})
            discover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
