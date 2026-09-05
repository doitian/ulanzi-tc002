"""TC002 custom-app HTTP sender. Python standard library only."""
import argparse
import json
from pathlib import Path
import re
import time
import sys
import urllib.request
from device import Device

COLORS = {
    "white": "#FFFFFF",
    "red": "#F07178",
    "orange": "#F2A65A",
    "yellow": "#E8CF78",
    "green": "#85C995",
    "mint": "#8ED8BD",
    "teal": "#70C5BF",
    "cyan": "#87D3E8",
    "blue": "#82AAE8",
    "purple": "#B39DDB",
    "pink": "#E8A0BF",
    "peach": "#EFB49B",
}


def resolve_color(value):
    value = value.strip()
    if value.lower() in COLORS:
        return COLORS[value.lower()]
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return value.upper()
    raise ValueError("Color must be #RRGGBB or one of: " + ", ".join(COLORS))


def device_get(device, path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://{device}{path}", timeout=5) as response:
        return json.load(response)


def text_frame(text, color="#FFFFFF", duration=10):
    if not text or any(not 32 <= ord(c) <= 126 for c in text):
        raise ValueError("Text must contain printable ASCII; use a bitmap frame for other scripts.")
    color = resolve_color(color)
    if duration <= 0:
        raise ValueError("Duration must be positive")
    element = {"content": text.upper(), "fontHeight": 10, "y": 3,
               "color": color, "rect": [0, 0, 52, 16], "x": 0}
    if len(text) <= 8:
        element.update(x=-1000, align="center")
    return {"duration": duration, "text": [element]}


def publish(device, app, frame):
    """POST a frame to a named custom app and check the device response."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        f"http://{device}/api/custom?name={app}",
        data=json.dumps(frame).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with opener.open(request, timeout=10) as response:
        body = response.read().decode("utf-8")
        try:
            result = json.loads(body)
        except ValueError:
            raise ValueError(f"Unexpected device response: {body[:200]}")
        if not isinstance(result, dict) or result.get("code") != 200:
            raise ValueError(f"Device rejected frame: {result}")
        return result


def scroll_frames(text, color):
    """A centered frame if text fits, otherwise a repeating marquee cycle."""
    frame = text_frame(text, color)
    element = frame["text"][0]
    width = len(element["content"]) * 6
    if width <= 52:
        yield frame
        return
    element.pop("align", None)
    from ansi_text import marquee_offsets
    for copies in marquee_offsets(width):
        elements = []
        for x in copies:
            if x < 52 and x + width > 0:
                # Clip offscreen character cells before sending; keep coordinates
                # near the screen and avoid the firmware's x=-1000 centering sentinel.
                skipped = max(0, -x // 6)
                content = element["content"][skipped:skipped + 10]
                elements.append(dict(element, content=content, x=x + skipped * 6))
        yield {"duration": 10, "text": elements}


def tail_text(args):
    from tail_client import follow_file
    lines = (line.removesuffix("\n").removesuffix("\r") for line in sys.stdin) if args.tail == "-" else follow_file(args.tail)
    for line in lines:
        args.send = line
        send_text(args)


def run_text_server(args):
    from text_server import serve
    serve(Device(args.device), args.app, args.host, args.port, args.tick,
          publish, scroll_frames)


def send_text(args):
    """Send one update to the widget server, without contacting the clock."""
    host = f"[{args.host}]" if ":" in args.host else args.host
    url = f"http://{host}:{args.port}/text"
    payload = {"text": args.send, "color": resolve_color(args.color)}
    if args.ansi:
        payload["ansi"] = True
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as response:
        result = json.load(response)
    if not isinstance(result, dict) or result.get("accepted") is not True:
        raise ValueError(f"Server rejected update: {result}")
    print(json.dumps(result), flush=True)


def run_frame(args):
    device = Device(args.device)
    while True:
        frame = json.loads(args.path.read_text(encoding="utf-8-sig"))
        if not isinstance(frame, dict):
            raise ValueError("Frame must be a JSON object")
        if args.dry_run:
            print(json.dumps(frame, indent=2))
            return
        print(json.dumps(device.post(publish, args.app, frame)), flush=True)
        if args.watch is None:
            return
        time.sleep(args.watch)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--device", help="Override the cached device IP")

    text = commands.add_parser("text", help="Text widget server and clients")
    actions = text.add_subparsers(dest="text_command", required=True)
    network = argparse.ArgumentParser(add_help=False)
    network.add_argument("--host", default="127.0.0.1", help="HTTP host (default: 127.0.0.1)")
    network.add_argument("--port", type=int, default=8008, help="HTTP port (default: 8008)")

    server = actions.add_parser("serve", parents=[common, network], help="Start the text widget HTTP server")
    server.add_argument("--tick", type=float, default=0.4, help="Seconds between scrolling frames")
    server.set_defaults(handler=run_text_server, app="text")

    styling = argparse.ArgumentParser(add_help=False)
    styling.add_argument("--color", default="white", help="Default color name or #RRGGBB (default: white)")
    styling.add_argument("--ansi", action="store_true", help="Interpret ANSI foreground colors")
    send = actions.add_parser("send", parents=[network, styling], help="Send text and exit")
    send.add_argument("send", metavar="TEXT", help="Message; empty text clears the screen")
    send.set_defaults(handler=send_text, app="text")
    tail = actions.add_parser("tail", parents=[network, styling], help="Follow the last line of a file or stdin")
    tail.add_argument("tail", metavar="PATH", help="UTF-8 file path, or - for stdin")
    tail.set_defaults(handler=tail_text, app="text")

    frame = commands.add_parser("frame", parents=[common], help="Send a custom JSON frame")
    frame.add_argument("--dry-run", action="store_true")
    frame.add_argument("path", type=Path)
    frame.add_argument("--watch", type=float, help="Read and refresh every N seconds")
    frame.set_defaults(handler=run_frame, app="frame")

    status = commands.add_parser("status", help="List device components")
    status.add_argument("--device", help="Override the cached device IP")
    status.set_defaults(handler=lambda args: print(json.dumps(
        device_get(Device(args.device).address, "/api/customList"), indent=2)))
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "text":
        if not 1 <= args.port <= 65535:
            parser.error("--port must be 1..65535")
        if args.text_command == "serve":
            if not 0 < args.tick < float("inf"):
                parser.error("--tick must be positive and finite")
        else:
            try:
                resolve_color(args.color)
                if args.text_command == "send":
                    if args.ansi:
                        from ansi_text import parse_ansi
                        parse_ansi(args.send, resolve_color(args.color))
                    elif len(args.send) > 256:
                        raise ValueError("Text cannot exceed 256 characters")
                    elif args.send:
                        text_frame(args.send, args.color)
            except ValueError as error:
                parser.error(str(error))
    if args.command == "frame" and args.watch is not None and not 0 < args.watch < float("inf"):
        parser.error("--watch must be positive and finite")
    args.handler(args)


def cli():
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))


if __name__ == "__main__":
    cli()
