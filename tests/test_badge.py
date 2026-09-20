import unittest

from ulanzi_tc002.client.agent_status import summarize
from ulanzi_tc002.client.badge import (
    BLACK, HEIGHT, OPENCODE_OUTER, PI_OUTER, STATUS_COLOR, WIDTH, badge_image, compose, png_bytes,
)


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

    def test_logo_uses_pi_color(self):
        pixels = compose("idle", 0, "pi")
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


if __name__ == "__main__":
    unittest.main()
