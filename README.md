# Ulanzi TC002 widgets

HTTP widgets for the 52x16 clock. Managed with uv; no runtime dependencies.

Install the command from this repository:

```powershell
uv tool install .
tc002 text serve
tc002 text send "HELLO WORLD" --color blue
tc002 text tail status.log --ansi
```

For an editable development installation, use `uv tool install --editable .`.
If `tc002` is not on PATH, run `uv tool update-shell` and open a new terminal.
After source changes, update a regular installation with `uv tool install --reinstall .`.

```powershell
uv sync
uv run tc002.py text serve
```

The text serve subcommand starts an HTTP server at `http://127.0.0.1:8008`.
It waits for clients; it does not change the clock until the first request.

From another terminal, send a message with the CLI:

```powershell
uv run tc002.py text send "HELLO WORLD" --color blue
uv run tc002.py text send ""
```

`text send` posts to the running server and exits. It defaults to white and uses
`127.0.0.1:8008`; `--host` and `--port` select another server address.
Use `text serve` to start the server. Use `text send TEXT` for one update or `text tail PATH` to follow new lines.

Follow a UTF-8 file or standard input:

```powershell
uv run tc002.py text tail status.log --color blue
uv run tc002.py text tail status.log --ansi --color white
Get-Content status.log -Tail 1 -Wait | uv run tc002.py text tail -
```

File mode sends the last existing line immediately, then checks every 0.25
seconds for new complete lines. If several arrive together, it sends the latest.
It follows file replacement/truncation and waits if the file is temporarily
missing. An initial final line without a newline is displayed; subsequent
partial lines wait for their terminating newline. Stdin mode forwards each line
as it arrives, sends a final unterminated line at EOF, and then exits.
A blank line clears the display. `--color` and `--ansi` apply to every update.
Stop file following with Ctrl+C.

Use `--ansi` to interpret foreground-color escape sequences. In PowerShell 7,
`` `e `` produces the actual ESC character:

```powershell
uv run tc002.py text send "`e[31mRED `e[34mBLUE`e[0m" --ansi
```

The HTTP equivalent is `{"text":"\u001b[31mRED \u001b[34mBLUE\u001b[0m","ansi":true}`.
Standard and bright ANSI colors (30–37, 90–97, indexed colors 0–15) use
[Catppuccin Mocha](https://github.com/catppuccin/palette). Red is `#F38BA8`,
blue `#89B4FA`, green `#A6E3A1`. `--color` sets the default foreground before
any ANSI color escape; SGR 0 and 39 restore it (white when omitted).
For example: `uv run tc002.py text send "DEFAULT" --ansi --color green`.
256-color (`38;5;N`) and truecolor (`38;2;R;G;B`) are also supported;
indices 16–255 and explicit RGB retain their standard/exact values.
Backgrounds and other SGR styles are ignored; cursor-control escapes are rejected.
ANSI codes do not count toward the 256-visible-character limit or scrolling width.
ANSI characters have a one-pixel gap; spaces reserve a full character cell.
This layout fits seven characters before scrolling (eight for plain text).
Empty text, or ANSI codes with no visible text, clears the screen.

```powershell
Invoke-RestMethod http://127.0.0.1:8008/text -Method Post -ContentType application/json -Body '{"text":"HELLO WORLD","color":"blue"}'

# Clear the screen
Invoke-RestMethod http://127.0.0.1:8008/text -Method Post -ContentType application/json -Body '{"text":""}'

# Read current message and any display connection error
Invoke-RestMethod http://127.0.0.1:8008/text
```

`POST /text` requires a string `text` (up to 256 printable ASCII characters).
Optional `color` accepts a case-insensitive name or `#RRGGBB`; it defaults to
white on every request. A 200 response confirms the clock accepted the first
frame. Invalid input returns 400, wrong content type 415, oversized body 413,
and device failures 502. The worker retries the latest message after device
failures; GET /text reports its latest error. State is held in memory.

Text that fits stays centered. Longer messages scroll continuously left,
start visible at the left edge, then repeat with a 26-pixel gap between copies. New messages restart the scroll.
Empty text sends an explicit black frame and stops the previous animation,
without deleting the device app. Static/blank frames refresh every five seconds.

Use the clock's knob to select the `text` DIY/custom app. The first POST creates
it automatically; POSTs do not automatically switch the visible app.
Keep the server running to animate and receive updates. Ctrl+C stops it.
Use `--port 8080` to change the port or `--host 0.0.0.0` to allow LAN clients.
The API has no authentication; its default listener is local to this PC.
`--tick 0.2` increases scroll speed. The server and text client use the `text` device app; the frame command uses
`frame`.

Named colors use softer RGB values:

| Name | Hex |
| --- | --- |
| white | `#FFFFFF` |
| red | `#F07178` |
| orange | `#F2A65A` |
| yellow | `#E8CF78` |
| green | `#85C995` |
| mint | `#8ED8BD` |
| teal | `#70C5BF` |
| cyan | `#87D3E8` |
| blue | `#82AAE8` |
| purple | `#B39DDB` |
| pink | `#E8A0BF` |
| peach | `#EFB49B` |

Other commands:

```powershell
uv run tc002.py status
uv run tc002.py frame frame.json --watch 5
```

The frame command sends custom-app JSON using the app name `frame`.

The device address is cached in `%LOCALAPPDATA%/ulanzi-tc002/device.json` on
Windows, or `$XDG_CONFIG_HOME/ulanzi-tc002/device.json` on Unix (default
`~/.config/ulanzi-tc002/device.json`). Existing source-tree `device.local.json`
settings are imported when no user cache exists. The cache is initially seeded
with this clock's known IP (10.31.3.197), MAC, and LAN (10.31.3.0/24).
Normal POSTs use the cached IP directly. Only connection failures or timeouts
trigger discovery: probe /getBase on the cached LAN and match the clock's MAC.
Retry the POST once at the discovered address, then save it for future runs.
HTTP rejection responses do not trigger discovery. No periodic IP lookup runs.
If the clock moves to another subnet, pass `--device NEW_IP`; after a successful
POST that address and its /24 discovery network are saved. Discovery supports
IPv4 networks of /24 or smaller, configurable in the cache file.

```powershell
uv run tc002.py text serve --device 10.31.3.197
uv run python -m unittest discover -s tests
```

Protocol references: [PixDeck core](https://github.com/cailurus/PixDeck/blob/main/pixbar_core.py)
and [notice plugin](https://github.com/cailurus/PixDeck/blob/main/plugins/notice/plugin.py).
