"""TC002 HTTP client."""
import argparse
import json
from pathlib import Path
import sys

from ulanzi_tc002.client.config import resolve_endpoint
from ulanzi_tc002.colors import resolve_color
from ulanzi_tc002.frames import image_data_uri, text_frame
from ulanzi_tc002.http import request


def server_url(args, path):
    return args.url.rstrip("/") + path


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
    result = api(args, f"/api/apps/{args.app}", method="POST", json_body=payload)
    if not isinstance(result, dict) or result.get("accepted") is not True:
        raise ValueError(f"Server rejected update: {result}")
    print(json.dumps(result), flush=True)


def tail_text(args):
    from ulanzi_tc002.client.tail import follow_file
    lines = (line.removesuffix("\n").removesuffix("\r") for line in sys.stdin) if args.tail == "-" else follow_file(args.tail)
    for line in lines:
        args.send = line
        send_text(args)


def send_image(args):
    payload = {"image": image_data_uri(Path(args.path).read_bytes())}
    result = api(args, f"/api/apps/{args.app}", method="POST", json_body=payload)
    if not isinstance(result, dict) or result.get("accepted") is not True:
        raise ValueError(f"Server rejected update: {result}")
    print(json.dumps(result), flush=True)


def apps_list(args):
    print(json.dumps(api(args, "/api/apps"), indent=2), flush=True)


def apps_show(args):
    print(json.dumps(api(args, f"/api/apps/{args.name}"), indent=2), flush=True)


def apps_create(args):
    print(json.dumps(api(args, "/api/apps", method="POST", json_body={"name": args.name, "type": args.type}), indent=2), flush=True)


def apps_delete(args):
    print(json.dumps(api(args, f"/api/apps/{args.name}", method="DELETE"), indent=2), flush=True)


def run_status(args):
    print(json.dumps(api(args, "/api/device"), indent=2), flush=True)


def run_watch(args):
    from ulanzi_tc002.client.watch import watch_agents
    watch_agents(args, api)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Server URL (default: config.toml or http://127.0.0.1:8008)")
    parser.add_argument("--host", help="Override server host")
    parser.add_argument("--port", type=int, help="Override server port")
    parser.add_argument("--token", help="Bearer token; defaults to config, gopass, or TC002_TOKEN")
    commands = parser.add_subparsers(dest="command", required=True)

    text = commands.add_parser("text", help="Text app client")
    actions = text.add_subparsers(dest="text_command", required=True)
    styling = argparse.ArgumentParser(add_help=False)
    styling.add_argument("--color", default="white", help="Default color name or #RRGGBB (default: white)")
    styling.add_argument("--ansi", action="store_true", help="Interpret ANSI foreground colors")
    send = actions.add_parser("send", parents=[styling], help="Send text and exit")
    send.add_argument("app", help="App name")
    send.add_argument("send", metavar="TEXT", help="Message; empty text clears the screen")
    send.set_defaults(handler=send_text)
    tail = actions.add_parser("tail", parents=[styling], help="Follow the last line of a file or stdin")
    tail.add_argument("app", help="App name")
    tail.add_argument("tail", metavar="PATH", help="UTF-8 file path, or - for stdin")
    tail.set_defaults(handler=tail_text)

    image = commands.add_parser("image", help="Image app client")
    image_actions = image.add_subparsers(dest="image_command", required=True)
    send_image_parser = image_actions.add_parser("send", help="Send a GIF or PNG")
    send_image_parser.add_argument("app", help="App name")
    send_image_parser.add_argument("path", metavar="FILE", help="GIF or PNG file")
    send_image_parser.set_defaults(handler=send_image)

    apps = commands.add_parser("apps", help="Create and delete apps")
    app_actions = apps.add_subparsers(dest="apps_command", required=True)
    app_actions.add_parser("list", help="List apps").set_defaults(handler=apps_list)
    show = app_actions.add_parser("show", help="Show one app")
    show.add_argument("name")
    show.set_defaults(handler=apps_show)
    create = app_actions.add_parser("create", help="Create an app")
    create.add_argument("type", choices=["text", "image"])
    create.add_argument("name")
    create.set_defaults(handler=apps_create)
    delete = app_actions.add_parser("delete", help="Delete an app")
    delete.add_argument("name")
    delete.set_defaults(handler=apps_delete)

    commands.add_parser("status", help="List device components").set_defaults(handler=run_status)

    watch = commands.add_parser("watch", help="Watch agent status")
    watch_sources = watch.add_subparsers(dest="watch_command", required=True)
    agents = watch_sources.add_parser("agents", help="Watch provider sessions")
    agents.add_argument("--providers", required=True, help="Comma-separated providers (opencode,claude)")
    agents.add_argument("--bridge-host", default="127.0.0.1", help="Bridge bind host (default: 127.0.0.1)")
    agents.add_argument("--bridge-port", type=int, default=8009, help="Bridge bind port (default: 8009)")
    agents.add_argument("--interval", type=float, default=1.0, help="Poll interval in seconds (default: 1)")
    agents.add_argument("--once", action="store_true", help="Poll once and exit")
    agents.set_defaults(handler=run_watch)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        endpoint = resolve_endpoint(args.url, args.host, args.port, args.token)
    except ValueError as error:
        parser.error(str(error))
    args.url, args.token, args.host, args.port = (
        endpoint["url"], endpoint["token"], endpoint["host"], endpoint["port"])
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
    if args.command == "image":
        try:
            image_data_uri(Path(args.path).read_bytes())
        except (OSError, ValueError) as error:
            parser.error(str(error))
    if args.command == "watch":
        from ulanzi_tc002.client.watch import parse_providers
        try:
            if args.interval <= 0:
                raise ValueError("interval must be positive")
            if not 0 <= args.bridge_port <= 65535:
                raise ValueError("bridge port must be 0..65535")
            args.providers = parse_providers(args.providers)
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
