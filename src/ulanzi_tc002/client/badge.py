import struct
import zlib

from ulanzi_tc002.frames import image_data_uri

WIDTH, HEIGHT, ICON = 52, 16, 16
BLACK = (0, 0, 0)
OPENCODE_OUTER = (183, 177, 177)
OPENCODE_INNER = (75, 70, 70)
STATUS_COLOR = {
    "ask": (242, 166, 90),
    "run": (232, 207, 120),
    "idle": (133, 201, 149),
}

_OPENCODE = (
    "################",
    "################",
    "################",
    "###..........###",
    "###..........###",
    "###..........###",
    "###.++++++++.###",
    "###.++++++++.###",
    "###.++++++++.###",
    "###.++++++++.###",
    "###.++++++++.###",
    "###.++++++++.###",
    "###.++++++++.###",
    "################",
    "################",
    "################",
)
_ASK = (
    "................",
    "......####......",
    ".....######.....",
    "....##....##....",
    "....##....##....",
    "..........##....",
    ".........##.....",
    "........##......",
    ".......##.......",
    ".......##.......",
    "................",
    ".......##.......",
    ".......##.......",
    "................",
    "................",
    "................",
)
_RUN = (
    "................",
    ".....##.........",
    ".....####.......",
    ".....#####......",
    ".....######.....",
    ".....#######....",
    ".....########...",
    ".....#######....",
    ".....######.....",
    ".....#####......",
    ".....####.......",
    ".....##.........",
    "................",
    "................",
    "................",
    "................",
)
_IDLE = (
    "................",
    "................",
    "....###...###...",
    "....###...###...",
    "....###...###...",
    "....###...###...",
    "....###...###...",
    "....###...###...",
    "....###...###...",
    "....###...###...",
    "....###...###...",
    "....###...###...",
    "................",
    "................",
    "................",
    "................",
)
_DIGITS = {
    "0": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "..##.", ".#...", "#....", "#####"),
    "3": (".###.", "#...#", "....#", ".###.", "....#", "#...#", ".###."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": (".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."),
}


def _sprite(rows, palette):
    return tuple(tuple(palette[ch] for ch in row) for row in rows)


def _paint(rows, color):
    return _sprite(rows, {".": BLACK, "#": color})


OPENCODE = _sprite(_OPENCODE, {"#": OPENCODE_OUTER, "+": OPENCODE_INNER, ".": BLACK})
STATUSES = {
    "ask": _paint(_ASK, STATUS_COLOR["ask"]),
    "run": _paint(_RUN, STATUS_COLOR["run"]),
    "idle": _paint(_IDLE, STATUS_COLOR["idle"]),
}


def _blit(canvas, sprite, x0, y0):
    for y, row in enumerate(sprite):
        dest_y = y0 + y
        if not 0 <= dest_y < HEIGHT:
            continue
        for x, pixel in enumerate(row):
            dest_x = x0 + x
            if pixel != BLACK and 0 <= dest_x < WIDTH:
                canvas[dest_y][dest_x] = pixel


def compose(kind, count, provider="opencode"):
    color = STATUS_COLOR[kind]
    digits = [_paint(_DIGITS[ch], color) for ch in str(count)] if count else []
    digit_w = 5 * len(digits) + max(0, len(digits) - 1) if digits else 0
    gap = 2
    width = ICON + gap + ICON if not digits else ICON + gap + digit_w + gap + ICON
    if width > WIDTH:
        gap = 1
        width = ICON + gap + ICON if not digits else ICON + gap + digit_w + gap + ICON
    x = max(0, (WIDTH - width) // 2)
    canvas = [[BLACK] * WIDTH for _ in range(HEIGHT)]
    _blit(canvas, OPENCODE, x, 0)
    x += ICON + gap
    if digits:
        y = (HEIGHT - 7) // 2
        for index, digit in enumerate(digits):
            _blit(canvas, digit, x + index * 6, y)
        x += digit_w + gap
    _blit(canvas, STATUSES[kind], x, 0)
    return canvas


def png_bytes(pixels):
    raw = b"".join(b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in pixels)
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", len(pixels[0]), len(pixels), 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def badge_image(kind, count, provider="opencode"):
    return image_data_uri(png_bytes(compose(kind, count, provider)))
