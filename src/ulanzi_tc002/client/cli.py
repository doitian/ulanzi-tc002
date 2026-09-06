"""TC002 HTTP client."""
import argparse
import json
import os
import sys

from ulanzi_tc002.colors import resolve_color
from ulanzi_tc002.frames import text_frame
from ulanzi_tc002.http import request


def server_url(args, path):
    host = f"[{args.host}]" if ":" in args.host else args.host
    return f"http://{host}:{args.port}{path}"


def api(args, path, method="GET", json_body=None, timeout=30):
    return request(
        server_url(args, path),
        method=method,
        json_body=json_body,
        timeout=timeout,
        token=args.token,
    )


def send_text(args):
    payload = {"text": args.send, "color": resolve_color(args.color)}
    if args.ansi:
        payload["ansi"] = True
    result = api(args, "/api/apps/text", method="POST", json_body=payload)
    if not isinstance(result, dict) or result.get("accepted") is not True:
        raise ValueError(f"Server rejected update: {result}")
    print(json.dumps(result), flush=True)


def tail_text(args):
    from ulanzi_tc002.client.tail import follow_file
    lines = (line.removesuffix("\n").removesuffix("\r") for line in sys.stdin) if args.tail == "-" else follow_file(args.tail)
    for line in lines:
        args.send = line
        send_text(args)


def apps_list(args):
    print(json.dumps(api(args, "/api/apps"), indent=2), flush=True)


def apps_show(args):
    print(json.dumps(api(args, f"/api/apps/{args.name}"), indent=2), flush=True)


def apps_enable(args):
    print(json.dumps(api(args, f"/api/apps/{args.name}/enable", method="POST", json_body={}), indent=2), flush=True)


def apps_disable(args):
    print(json.dumps(api(args, f"/api/apps/{args.name}/disable", method="POST", json_body={}), indent=2), flush=True)


def run_status(args):
    print(json.dumps(api(args, "/api/device"), indent=2), flush=True)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("TC002_SERVER_HOST", "127.0.0.1"),
                        help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TC002_SERVER_PORT", "8008")),
                        help="Server port (default: 8008)")
    parser.add_argument("--token", default=os.environ.get("TC002_TOKEN"),
                        help="Bearer token; defaults to TC002_TOKEN")
    commands = parser.add_subparsers(dest="command", required=True)

    text = commands.add_parser("text", help="Text app client")
    actions = text.add_subparsers(dest="text_command", required=True)
    styling = argparse.ArgumentParser(add_help=False)
    styling.add_argument("--color", default="white", help="Default color name or #RRGGBB (default: white)")
    styling.add_argument("--ansi", action="store_true", help="Interpret ANSI foreground colors")
    send = actions.add_parser("send", parents=[styling], help="Send text and exit")
    send.add_argument("send", metavar="TEXT", help="Message; empty text clears the screen")
    send.set_defaults(handler=send_text)
    tail = actions.add_parser("tail", parents=[styling], help="Follow the last line of a file or stdin")
    tail.add_argument("tail", metavar="PATH", help="UTF-8 file path, or - for stdin")
    tail.set_defaults(handler=tail_text)

    apps = commands.add_parser("apps", help="List and enable apps")
    app_actions = apps.add_subparsers(dest="apps_command", required=True)
    app_actions.add_parser("list", help="List apps").set_defaults(handler=apps_list)
    show = app_actions.add_parser("show", help="Show one app")
    show.add_argument("name")
    show.set_defaults(handler=apps_show)
    enable = app_actions.add_parser("enable", help="Enable an app")
    enable.add_argument("name")
    enable.set_defaults(handler=apps_enable)
    disable = app_actions.add_parser("disable", help="Disable an app")
    disable.add_argument("name")
    disable.set_defaults(handler=apps_disable)

    commands.add_parser("status", help="List device components").set_defaults(handler=run_status)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be 1..65535")
    if args.command == "text":
        try:
            resolve_color(args.color)
            if args.text_command == "send":
                if args.ansi:
                    from ulanzi_tc002.ansi_text import parse_ansi
                    parse_ansi(args.send, resolve_color(args.color))
                elif len(args.send) > 256:
                    raise ValueError("Text cannot exceed 256 characters")
                elif args.send:
                    text_frame(args.send, args.color)
        except ValueError as error:
            parser.error(str(error))
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
