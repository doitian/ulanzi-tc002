# OpenCode session counts

`tc002 watch agents --providers opencode` shows one status and one number on
the clock. That number is not "how many chats exist". It is an aggregate of
sessions that this process has seen go ASK or RUN, across every OpenCode
instance that is still posting to the local bridge.

## Pipeline

```
OpenCode events  →  plugin (per process)  →  POST /providers/opencode
                                                      ↓
clock badge  ←  summarize()  ←  BridgeStore.snapshot()
```

1. `watch agents` starts a bridge (default `http://127.0.0.1:8009`) and
   installs `~/.config/opencode/plugins/tc002-watch.js` with that URL.
2. Each OpenCode process loads the plugin and POSTs once a second:
   `{ id: "<pid>", status: { <session>: "busy"|"idle" }, blocking: [<session>] }`.
3. The bridge keeps one record per `(provider, pid)`.
4. `snapshot("opencode")` merges those records, then `summarize()` picks
   the badge kind and the displayed count.

Restart both `tc002 watch agents` and OpenCode after changing the plugin.

## What the plugin reports

The plugin does not list historical chats. A session enters `seen` only when
it becomes `busy`/`retry`, or when a permission/question is asked.

| Set | Meaning |
| --- | --- |
| `seen` | Sessions that already went ASK or RUN |
| `running` | Subset of `seen` that is currently `busy` or `retry` |
| `pending` | Sessions blocked on permission or question |
| `child` | Subagent sessions (`session.created` with `parentID`) |

Each flush sends `status[sid] = running ? "busy" : "idle"` for every `seen`
id, and `blocking` as the unique session ids in `pending`.

`retry` is treated as running in both the plugin and `summarize()`.

### Idle chats

Shared rules: [idle-chats.md](idle-chats.md). The plugin prunes idle sessions
in this process when:

- a top-level session is created (`session.created` without `parentID`)
- the TUI selects a session (`tui.session.select`)
- `/new` runs (`tui.command.execute` with `session.new`)
- a top-level session already in `seen` goes idle

`/new` only goes home; `/sessions` only switches the focused chat.
Permission/question `asked`/`updated` adds the session to `pending` even when
that chat is not focused. `replied`/`rejected` clears that request. The
session stays in `seen`. Child sessions are `session.created` with
`parentID`. `session.deleted` drops the id everywhere.

## Bridge merge

`BridgeStore` keys instances by `(provider, id)` where `id` is the OpenCode
pid. A later POST from the same pid replaces the previous payload.

`snapshot()`:

1. Drops any instance with no POST for 5 seconds (process quit).
2. Prefixes each session id with `"{pid}:"` so two processes cannot collide.
3. Unions `blocking` the same way.
4. Calls `summarize(status_by_id, blocking)`.

Several OpenCode windows therefore add. Two pids each with one busy session
are RUN 2.

## `summarize`

A session in `blocking` is ASK, even if `status` still says `busy`. The same
session is not also counted as RUN.

```
ask  = |blocking|
run  = sessions whose status is busy/retry and that are not blocking
idle = sessions whose status is idle and that are not blocking
```

Displayed kind is the first of ASK, RUN, IDLE that has a non-zero count, or
IDLE when nothing is tracked:

| Condition | Kind | Count on the badge |
| --- | --- | --- |
| `ask > 0` | `ask` | `ask` |
| else `run > 0` | `run` | `run` |
| else | `idle` | `idle` (0 if `seen` is empty) |

The clock omits a displayed 0 and caps at `9+`. The CLI still prints the
three raw totals: `opencode RUN 1 (ask=0 run=1 idle=1)`.
