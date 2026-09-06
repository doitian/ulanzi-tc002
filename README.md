# Ulanzi TC002 widgets

HTTP widgets for the 52x16 clock. The server owns the device and all apps.
The `tc002` CLI is an HTTP client. Managed with uv.

## Run the server

Docker (recommended):

```powershell
docker compose up --build
```

Or locally:

```powershell
uv sync --extra server
uv run tc002-server
```

The server listens at `http://127.0.0.1:8008` (Docker binds `0.0.0.0:8008`).
Open that URL for the web UI. MCP is at `/mcp`. Select the `text` DIY app on
the clock knob. The first text POST creates it; POSTs do not switch the visible app.

```powershell
uv run tc002 text send "HELLO WORLD" --color blue
uv run tc002 text send ""
uv run tc002 text tail status.log --ansi
uv run tc002 apps list
uv run tc002 apps disable text
uv run tc002 apps enable text
uv run tc002 status
```

`text send` and `text tail` post to the server and never talk to the clock.
File tailing still follows rotation, truncation, and a missing file; a blank
line clears the display.

## HTTP API

```powershell
Invoke-RestMethod http://127.0.0.1:8008/api/apps/text -Method Post -ContentType application/json -Body '{"text":"HELLO WORLD","color":"blue"}'
Invoke-RestMethod http://127.0.0.1:8008/api/apps/text
Invoke-RestMethod http://127.0.0.1:8008/api/apps
Invoke-RestMethod http://127.0.0.1:8008/api/apps/text/disable -Method Post
```

`GET/POST /text` is an alias for the text app. `POST /api/apps/text` requires a
string `text` (up to 256 printable ASCII characters). Optional `color` accepts a
case-insensitive name or `#RRGGBB`; it defaults to white. Optional `ansi`
interprets foreground-color escapes. Invalid input returns 400; a disabled app
returns 409; device failures return 502. Empty text, or ANSI with no visible
characters, sends a black frame without deleting the DIY app.

Text that fits stays centered. Longer messages scroll left. Static/blank frames
refresh every five seconds while the server runs.

Named colors: white, red, orange, yellow, green, mint, teal, cyan, blue, purple,
pink, peach. ANSI colors use [Catppuccin Mocha](https://github.com/catppuccin/palette).

## Auth, proxy, device

The CLI reads `~/.config/ulanzi-tc002/config.toml` (`$XDG_CONFIG_HOME` if set):

```toml
url = "http://127.0.0.1:8008"
token = "optional"
```

`[server] url` / `token` work too. `--url`, `--host`, `--port`, `--token` and
`TC002_SERVER_URL` override the file. `--host` / `--port` change parts of the URL.

If `TC002_TOKEN` is set, API, UI, and MCP require `Authorization: Bearer`.
`GET /api/health` stays open. The CLI uses `--token`, the config file, or `TC002_TOKEN`.

Outbound HTTP uses `TC002_HTTP_PROXY` or `HTTP_PROXY`. Destinations on LAN
(RFC1918, loopback, link-local, ULA), `localhost`, and `NO_PROXY` skip the
proxy. Clock traffic is LAN, so it is never proxied.

Device cache lives in `%LOCALAPPDATA%/ulanzi-tc002` on Windows, or
`$XDG_CONFIG_HOME/ulanzi-tc002` on Unix. Docker uses `/data`. Override with
`TC002_DATA_DIR`. If `device.json` is missing and `TC002_DEVICE_IP` is unset,
the server scans local `/24`s for the clock MAC. Set `TC002_DEVICE_NETWORK` when
the clock is not on those interfaces.

| Variable | Role |
| --- | --- |
| `TC002_HOST` / `TC002_PORT` | Server bind (default `127.0.0.1:8008`; Docker `0.0.0.0`) |
| `TC002_SERVER_URL` | CLI server endpoint |
| `TC002_SERVER_HOST` / `TC002_SERVER_PORT` | CLI host/port overrides |
| `TC002_TOKEN` | Optional bearer token |
| `TC002_CLIENT_CONFIG` | Alternate client config.toml path |
| `TC002_HTTP_PROXY` | Outbound proxy; LAN skipped |
| `TC002_DEVICE_IP` / `TC002_DEVICE_MAC` / `TC002_DEVICE_NETWORK` | Clock identity |
| `TC002_DATA_DIR` | Config and device cache |
| `TC002_TICK` | Scroll interval in seconds |

## MCP

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "tc002": {
      "type": "remote",
      "url": "http://127.0.0.1:8008/mcp",
      "enabled": true,
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:TC002_TOKEN}"
      }
    }
  }
}
```

Tools: `list_apps`, `get_app`, `enable_app`, `disable_app`, `text_send`, `text_get`.

## Docker image

GitHub Actions publishes `ghcr.io/doitian/ulanzi-tc002` from `main` and `v*` tags.

```powershell
docker pull ghcr.io/doitian/ulanzi-tc002:latest
docker run --rm -p 8008:8008 -v tc002-data:/data ghcr.io/doitian/ulanzi-tc002:latest
```

```powershell
uv sync --extra server
uv run python -m unittest discover -s tests
```

Install the CLI without server extras: `uv tool install .`
Install with the server: `uv tool install ".[server]"`.

Protocol references: [PixDeck core](https://github.com/cailurus/PixDeck/blob/main/pixbar_core.py)
and [notice plugin](https://github.com/cailurus/PixDeck/blob/main/plugins/notice/plugin.py).
