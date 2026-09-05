"""ANSI SGR foreground colors for the TC002 pixel text renderer."""
import re

# Catppuccin Mocha: https://github.com/catppuccin/palette
PALETTE = ["#45475A", "#F38BA8", "#A6E3A1", "#F9E2AF",
           "#89B4FA", "#F5C2E7", "#94E2D5", "#BAC2DE",
           "#585B70", "#F38BA8", "#A6E3A1", "#F9E2AF",
           "#89B4FA", "#F5C2E7", "#94E2D5", "#A6ADC8"]
SGR = re.compile(r"\x1b\[([0-9;]*)m")
GLYPH_WIDTH = 6
# Measured on the device font at fontHeight 10 (parse_ansi uppercases all
# input); glyphs not listed here are GLYPH_WIDTH pixels wide.
GLYPH_WIDTHS = {"M": 8, "N": 7, "W": 8, "X": 8,
                **{digit: 5 for digit in "0123456789"}}


def glyph_width(char):
    return GLYPH_WIDTHS.get(char, GLYPH_WIDTH)


def text_width(glyphs):
    return max(0, sum(glyph_width(char) + 1 for char, _ in glyphs) - 1)


def marquee_offsets(width):
    """One repeating cycle, initially visible, with a half-screen gap."""
    period = width + 26
    offset = 0
    while offset > -period:
        yield offset, offset + period
        offset -= min(5, period + offset)


def indexed_color(index):
    if not 0 <= index <= 255:
        raise ValueError("ANSI palette index must be 0..255")
    if index < 16:
        return PALETTE[index]
    if index >= 232:
        value = 8 + 10 * (index - 232)
        return f"#{value:02X}{value:02X}{value:02X}"
    index -= 16
    levels = [0, 95, 135, 175, 215, 255]
    return "#" + "".join(f"{levels[n]:02X}" for n in
                          [index // 36, index // 6 % 6, index % 6])


def parse_ansi(text, default):
    """Return visible (character, foreground) pairs; ignore non-color SGR styles."""
    color, result, position = default, [], 0
    if len(text) > 4096:
        raise ValueError("ANSI text cannot exceed 4096 characters including escapes")
    while position < len(text):
        char = text[position]
        if char != "\x1b":
            if not 32 <= ord(char) <= 126:
                raise ValueError("Visible text must be printable ASCII")
            result.append((char.upper(), color))
            if len(result) > 256:
                raise ValueError("Text cannot exceed 256 visible characters")
            position += 1
            continue
        match = SGR.match(text, position)
        if match is None:
            raise ValueError("Only ANSI SGR escapes (ESC[...m) are supported")
        codes = [int(value or 0) for value in match[1].split(";")]
        i = 0
        while i < len(codes):
            code = codes[i]
            if code in (0, 39):
                color = default
            elif 30 <= code <= 37:
                color = PALETTE[code - 30]
            elif 90 <= code <= 97:
                color = PALETTE[code - 90 + 8]
            elif code in (38, 48):
                # Consume background color arguments too, but don't render them.
                if i + 1 >= len(codes):
                    raise ValueError("Incomplete ANSI color escape")
                mode = codes[i + 1]
                count = 1 if mode == 5 else 3 if mode == 2 else 0
                values = codes[i + 2:i + 2 + count]
                if not count or len(values) != count or any(not 0 <= n <= 255 for n in values):
                    raise ValueError("Expected ANSI 38;5;N or 38;2;R;G;B color")
                selected = indexed_color(values[0]) if mode == 5 else "#" + "".join(f"{n:02X}" for n in values)
                if code == 38:
                    color = selected
                i += count + 1
            i += 1
        position = match.end()
    return result


def ansi_frames(glyphs):
    """Lay out colored characters with a one-pixel gap and scroll as a unit."""
    from text_server import blank_frame
    width = text_width(glyphs)
    if not width:
        yield blank_frame()
        return
    offsets = [((52 - width) // 2,)] if width <= 52 else marquee_offsets(width)
    starts = []
    left = 0
    for char, _ in glyphs:
        starts.append(left)
        left += glyph_width(char) + 1
    for copies in offsets:
        elements = []
        for x in copies:
            for (char, color), start in zip(glyphs, starts):
                left = x + start
                # Spaces reserve their full advance without relying on a space glyph.
                if char != " " and left < 52 and left + glyph_width(char) > 0:
                    elements.append({"content": char, "fontHeight": 10,
                                     "x": left, "y": 3, "color": color,
                                     "rect": [0, 0, 52, 16]})
        frame = blank_frame()
        frame["text"] = elements
        # Avoid a black draw command overlaying text on firmware that draws last.
        if elements:
            frame.pop("draw")
        yield frame
