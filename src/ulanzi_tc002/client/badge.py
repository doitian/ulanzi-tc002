import struct
import zlib

from ulanzi_tc002.frames import image_data_uri

WIDTH, HEIGHT, ICON = 52, 16, 16
BLACK = (0, 0, 0)
OPENCODE_OUTER = (183, 177, 177)
OPENCODE_INNER = (75, 70, 70)
CLAUDE_OUTER = (217, 119, 87)
CLAUDE_INNER = (140, 62, 41)
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
_CLAUDE = (
    "................",
    "................",
    "................",
    ".##############.",
    ".##############.",
    ".##.########.##.",
    ".##.########.##.",
    "################",
    "################",
    ".##############.",
    ".##############.",
    "..##.##..##.##..",
    "..##.##..##.##..",
    "................",
    "................",
    "................",
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
    "+": (".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."),
}


def _sprite(rows, palette):
    return tuple(tuple(palette[ch] for ch in row) for row in rows)


def _paint(rows, color):
    return _sprite(rows, {".": BLACK, "#": color})


OPENCODE = _sprite(_OPENCODE, {"#": OPENCODE_OUTER, "+": OPENCODE_INNER, ".": BLACK})
CLAUDE = _sprite(_CLAUDE, {"#": CLAUDE_OUTER, "+": CLAUDE_INNER, ".": BLACK})
LOGOS = {"opencode": OPENCODE, "claude": CLAUDE}
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


def _vcenter(sprite):
    rows = [i for i, row in enumerate(sprite) if any(pixel != BLACK for pixel in row)]
    if not rows:
        return 0
    return (HEIGHT - (rows[-1] - rows[0] + 1)) // 2 - rows[0]


def _hcenter(sprite, box=ICON):
    cols = [i for i in range(len(sprite[0])) if any(row[i] != BLACK for row in sprite)]
    if not cols:
        return 0
    return (box - (cols[-1] - cols[0] + 1)) // 2 - cols[0]


def compose(kind, count, provider="opencode"):
    color = STATUS_COLOR[kind]
    text = "9+" if count > 9 else str(count) if count else ""
    digits = [_paint(_DIGITS[ch], color) for ch in text]
    gap = 2
    width = ICON + gap + ICON + gap + 11
    x = max(0, (WIDTH - width) // 2)
    canvas = [[BLACK] * WIDTH for _ in range(HEIGHT)]
    logo = LOGOS.get(provider, OPENCODE)
    _blit(canvas, logo, x + _hcenter(logo), _vcenter(logo))
    x += ICON + gap
    _blit(canvas, STATUSES[kind], x, _vcenter(STATUSES[kind]))
    if digits:
        x += ICON + gap
        y = (HEIGHT - 7) // 2
        for index, digit in enumerate(digits):
            _blit(canvas, digit, x + index * 6, y)
    return canvas


def png_bytes(pixels):
    raw = b"".join(b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in pixels)
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", len(pixels[0]), len(pixels), 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def badge_image(kind, count, provider="opencode"):
    return image_data_uri(png_bytes(compose(kind, count, provider)))
