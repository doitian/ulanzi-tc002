import unittest
from unittest.mock import Mock

from ulanzi_tc002.frames import blank_frame, image_data_uri, image_frame, parse_image
from ulanzi_tc002.server.apps.image import ImageWidget

GIF = b"GIF89a" + b"\x00" * 8
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


class ImageTests(unittest.TestCase):
    def test_gif_and_png_data_uris(self):
        self.assertTrue(image_data_uri(GIF).startswith("data:image/gif;base64,"))
        self.assertTrue(image_data_uri(PNG).startswith("data:image/png;base64,"))
        frame = image_frame(image_data_uri(GIF))
        self.assertEqual(frame["image"][0]["position"], [0, 0])
        self.assertEqual(parse_image(image_data_uri(GIF)), image_data_uri(GIF))

    def test_rejects_non_gif_png_and_bad_base64(self):
        with self.assertRaises(ValueError):
            image_data_uri(b"not-an-image")
        with self.assertRaises(ValueError):
            parse_image("%%%")
        with self.assertRaises(ValueError):
            parse_image("data:image/gif,not-base64")

    def test_widget_update_and_clear(self):
        device = Mock()
        widget = ImageWidget(device, "cat")
        result = widget.update({"image": image_data_uri(GIF)})
        self.assertTrue(result["accepted"])
        self.assertEqual(device.post.call_args.args[1], "cat")
        self.assertEqual(device.post.call_args.args[2]["image"][0]["data"], image_data_uri(GIF))
        widget.update({"image": ""})
        self.assertEqual(device.post.call_args.args[2], blank_frame())
        self.assertEqual(widget.state[0], "")
