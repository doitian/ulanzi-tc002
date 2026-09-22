import unittest

from ulanzi_tc002.client.badge import (
    BLACK, HEIGHT, OPENCODE_OUTER, PI_OUTER, STATUS_COLOR, WIDTH, badge_image, compose, png_bytes,
)


class BadgeTests(unittest.TestCase):
    def test_canvas_size_and_status_color(self):
        pixels = compose("waiting", 2)
        self.assertEqual(len(pixels), HEIGHT)
        self.assertTrue(all(len(row) == WIDTH for row in pixels))
        self.assertIn(STATUS_COLOR["waiting"], {pixel for row in pixels for pixel in row})
        self.assertNotIn(STATUS_COLOR["running"], {pixel for row in pixels for pixel in row})
        idle = {pixel for row in compose("idle", 0) for pixel in row}
        self.assertIn(STATUS_COLOR["idle"], idle)
        self.assertIn(BLACK, idle)
        self.assertTrue(png_bytes(pixels).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(badge_image("waiting", 2).startswith("data:image/png;base64,"))

    def test_count_caps_at_nine_plus(self):
        self.assertNotEqual(compose("waiting", 9), compose("waiting", 10))
        self.assertEqual(compose("waiting", 10), compose("waiting", 11))

    def test_icons_stay_put_when_count_changes(self):
        def logo(pixels):
            return tuple(
                (x, y)
                for y, row in enumerate(pixels)
                for x, pixel in enumerate(row)
                if pixel == OPENCODE_OUTER
            )
        none = logo(compose("waiting", 0))
        self.assertEqual(none, logo(compose("waiting", 1)))
        self.assertEqual(none, logo(compose("waiting", 12)))

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
