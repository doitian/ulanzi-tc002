import unittest
from unittest.mock import Mock
from ansi_text import parse_ansi, ansi_frames
from text_server import TextWidget, blank_frame
import tc002


class AnsiTests(unittest.TestCase):
    def test_mocha_colors_and_reset(self):
        glyphs = parse_ansi("\x1b[31mR\x1b[94mB\x1b[0mW", "#FFFFFF")
        self.assertEqual(glyphs, [("R", "#F38BA8"), ("B", "#89B4FA"), ("W", "#FFFFFF")])

    def test_requested_default_color_before_and_after_ansi_reset(self):
        glyphs = parse_ansi("A\x1b[31mB\x1b[0mC\x1b[34mD\x1b[39mE", "#85C995")
        self.assertEqual([color for _, color in glyphs],
                         ["#85C995", "#F38BA8", "#85C995", "#89B4FA", "#85C995"])
        widget = TextWidget(Mock(), "text", 0.4, tc002.publish, tc002.scroll_frames)
        widget.update({"text": "A\x1b[31mB\x1b[0mC", "color": "green", "ansi": True})
        self.assertEqual([color for _, color in widget.glyphs],
                         ["#85C995", "#F38BA8", "#85C995"])

    def test_extended_colors_and_background_consumption(self):
        glyphs = parse_ansi("\x1b[38;2;10;20;30mA\x1b[48;2;31;32;33mB\x1b[38;5;196mC", "#FFFFFF")
        self.assertEqual([c for _, c in glyphs], ["#0A141E", "#0A141E", "#FF0000"])

    def test_visible_length_controls_centering_and_scroll(self):
        short = list(ansi_frames(parse_ansi("\x1b[31mHI\x1b[0m", "#FFFFFF")))
        self.assertEqual(len(short), 1)
        self.assertEqual([t["x"] for t in short[0]["text"]], [19, 26])
        long = list(ansi_frames(parse_ansi("\x1b[31mHELLO \x1b[34mWORLD", "#FFFFFF")))
        self.assertEqual(long[0]["text"][0]["x"], 0)
        self.assertTrue(all(frame["text"] for frame in long))
        visible = next(f for f in long if len(f["text"]) > 1)
        self.assertEqual(visible["text"][1]["x"] - visible["text"][0]["x"], 7)

    def test_spaces_reserve_width_across_color_changes(self):
        frame = next(ansi_frames(parse_ansi("A \x1b[31mB", "#FFFFFF")))
        self.assertEqual([t["content"] for t in frame["text"]], ["A", "B"])
        self.assertEqual(frame["text"][1]["x"] - frame["text"][0]["x"], 14)

    def test_spacing_changes_overflow_boundary(self):
        widget = TextWidget(Mock(), "text", 0.4, tc002.publish, tc002.scroll_frames)
        widget.update({"text": "12345678", "ansi": True})
        self.assertEqual(widget.rendered_width, 55)
        self.assertEqual(widget.device.post.call_args.args[2]["text"][0]["x"], 0)

    def test_measured_wide_glyphs_get_extra_space(self):
        ma = next(ansi_frames(parse_ansi("MA", "#FFFFFF")))
        self.assertEqual([t["x"] for t in ma["text"]], [18, 27])
        na = next(ansi_frames(parse_ansi("NA", "#FFFFFF")))
        self.assertEqual([t["x"] for t in na["text"]], [19, 27])
        wa = next(ansi_frames(parse_ansi("WA", "#FFFFFF")))
        self.assertEqual([t["x"] for t in wa["text"]], [18, 27])
        xa = next(ansi_frames(parse_ansi("XA", "#FFFFFF")))
        self.assertEqual([t["x"] for t in xa["text"]], [18, 27])

    def test_bad_escapes_rejected(self):
        for text in ["\x1b[2J", "\x1b[38;2;1mX", "\x1b[38;5;256mX", "\x1b[31"]:
            with self.assertRaises(ValueError):
                parse_ansi(text, "#FFFFFF")

    def test_api_ansi_and_reset_only_clear(self):
        widget = TextWidget(Mock(), "text", 0.4, tc002.publish, tc002.scroll_frames)
        result = widget.update({"text": "\x1b[31mHI", "ansi": True})
        self.assertTrue(result["ansi"])
        self.assertEqual(widget.visible_length, 2)
        self.assertEqual(widget.device.post.call_args.args[2]["text"][0]["color"], "#F38BA8")
        widget.update({"text": "\x1b[0m", "ansi": True})
        self.assertEqual(widget.device.post.call_args.args[2], blank_frame())
        widget.update({"text": "HI"})
        self.assertFalse(widget.ansi)
