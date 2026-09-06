# Ulanzi TC002 widgets

HTTP widgets for the 52x16 clock. The server owns the device and all apps.
The `tc002` CLI is an HTTP client. Managed with uv.

Create as many text and image apps as you want. Each app name is a DIY page on
the clock; use the knob to cycle between them.

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
Open that URL for the web UI. MCP is at `/mcp`. The first POST to an app creates
that DIY page on the clock; later POSTs update it and do not switch the visible
app. Created apps are saved and restored when the server restarts.

```powershell
uv run tc002 apps create text hello
uv run tc002 text send hello "HELLO WORLD" --color blue
uv run tc002 text send hello ""
uv run tc002 text tail hello status.log --ansi
uv run tc002 apps create image cat
uv run tc002 image send cat cat.gif
uv run tc002 apps list
uv run tc002 apps delete hello
uv run tc002 status
```

`text send`, `text tail`, and `image send` post to the server and never talk to
the clock. File tailing still follows rotation, truncation, and a missing file;
a blank line clears the display.

## HTTP API

```powershell
Invoke-RestMethod http://127.0.0.1:8008/api/apps -Method Post -ContentType application/json -Body '{"name":"hello","type":"text"}'
Invoke-RestMethod http://127.0.0.1:8008/api/apps/hello -Method Post -ContentType application/json -Body '{"text":"HELLO WORLD","color":"blue"}'
Invoke-RestMethod http://127.0.0.1:8008/api/apps
Invoke-RestMethod http://127.0.0.1:8008/api/apps/hello -Method Delete
Invoke-RestMethod http://127.0.0.1:8008/api/apps -Method Post -ContentType application/json -Body '{"name":"cat","type":"image"}'
Invoke-RestMethod http://127.0.0.1:8008/api/apps/cat -Method Post -ContentType application/json -Body '{"image":"data:image/gif;base64,..."}'
```

`POST /api/apps` requires `name` (1-32 letters, digits, `_` or `-`) and `type`
(`text` or `image`). Duplicate names return 409. `DELETE /api/apps/{name}`
removes the app from the server and the clock.

`POST /api/apps/{name}` on a text app requires a string `text` (up to 256
printable ASCII characters). Optional `color` accepts a case-insensitive name or
`#RRGGBB`; it defaults to white. Optional `ansi` interprets foreground-color
escapes. Empty text, or ANSI with no visible characters, sends a black frame
without deleting the DIY app.

`POST /api/apps/{name}` on an image app requires `image`: a GIF or PNG as a
`data:image/...;base64,...` URI or raw base64 (up to 2 MiB). The server fits the
image into the 52x16 canvas. Animated GIFs stay GIFs and loop on the device.
Empty `image` sends a black frame. Optional `duration` is how long the clock
shows that DIY page.

Invalid input returns 400; unknown apps return 404; device failures return 502.

Text that fits stays centered. Longer messages scroll left. Static/blank text
frames refresh every five seconds while the server runs.

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
the server scans local `/24`s for the clock MAC. Docker bridge networks are
skipped; run with host networking so the scan sees the LAN, or set
`TC002_DEVICE_IP` / `TC002_DEVICE_NETWORK`.

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

Tools: `list_apps`, `get_app`, `create_app`, `delete_app`, `text_send`,
`text_get`, `image_send`, `image_get`.

## Docker image

GitHub Actions publishes `ghcr.io/doitian/ulanzi-tc002` from `main` and `v*` tags
(`linux/amd64`, `linux/arm64`, and `linux/arm/v7`).

```powershell
docker pull ghcr.io/doitian/ulanzi-tc002:latest
docker run --rm --network host -v tc002-data:/data ghcr.io/doitian/ulanzi-tc002:latest
```

```powershell
uv sync --extra server
uv run python -m unittest discover -s tests
```

Install the CLI without server extras: `uv tool install .`
Install with the server: `uv tool install ".[server]"`.

Protocol references: [PixDeck core](https://github.com/cailurus/PixDeck/blob/main/pixbar_core.py)
and [notice plugin](https://github.com/cailurus/PixDeck/blob/main/plugins/notice/plugin.py).
