# Claude session counts

`tc002 watch agents --providers claude` shows one status and one number on
the clock. That number is not "how many chats exist". It is an aggregate of
Claude Code sessions that have gone ASK or RUN, from both the Desktop app and
the CLI, as long as they are still live in the local bridge.

## Pipeline

```
Desktop + CLI hooks  →  POST /providers/claude  (hook_event_name)
claude agents --json →  BridgeStore.merge_agents("claude")
                                    ↓
clock badge  ←  summarize()  ←  BridgeStore.snapshot()
```

1. `watch agents` starts a bridge (default `http://127.0.0.1:8009`) and
   merges HTTP hooks into `~/.claude/settings.json` with that URL.
2. Claude Code fires the same hooks in the terminal, the Desktop app, the IDE
   extension, and the web. Each event POSTs to `/providers/claude`.
3. `watch agents` also polls `claude agents --json` so CLI sessions that were
   already live appear without waiting for the next hook.
4. The bridge keeps hook-tracked sessions in one map, then posts two instance
   records: `desktop` and `cli`.
5. `snapshot("claude")` merges those records, then `summarize()` picks the
   badge kind and the displayed count.

Restart `tc002 watch agents` after changing hooks. Already-open Claude
sessions pick up the hooks on their next event. If watch did not exit
cleanly, run `tc002 watch agents --teardown` to remove leftover hooks.

## What the hooks report

Hooks do not list historical chats. A session enters the map only when it
becomes busy, or when a permission / elicitation / notification asks for
input.

| Event | Effect |
| --- | --- |
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse` | `status = busy`, clear blocking |
| `PermissionRequest`, `Elicitation` | blocking (ASK) |
| `Notification` of `permission_prompt`, `agent_needs_input`, `elicitation_dialog`, `elicitation_url_dialog` | blocking (ASK) |
| `Stop`, `StopFailure` | `status = idle`, then prune |
| `SessionStart` | prune only; the new chat is not counted until ASK or RUN |
| `SessionEnd` | drop |

`retry` is not a Claude hook status. `summarize()` still treats `busy` and
`retry` as running if an agents row ever sends `retry`.

Desktop vs CLI is `entrypoint` containing `desktop`, else a match against
`cliSessionId` / `sessionId` in Claude Desktop's session files, else `cli`.

### Idle chats

Shared rules: [idle-chats.md](idle-chats.md). `prune(keep, source)` drops idle
sessions of that source when:

- a session starts (`SessionStart`: startup, resume, clear, fork)
- the user submits a prompt (`UserPromptSubmit`)
- a session already in the map goes idle (`Stop`, `StopFailure`)

A new Desktop session, `/clear`, `/resume`, or a new CLI session only switches
focus. Permission / elicitation / ask notifications add the session even when
that chat is not focused. Subagent turns use `agent_id`. Sessions from
`claude agents --json` carry a `pid`; prune skips a different pid so a second
CLI terminal is not dropped when the first runs `/clear`.

## Bridge merge

`BridgeStore` keys instances by `(provider, id)`. For Claude the ids are
`desktop` and `cli`, rebuilt on every hook or agents poll. Direct POSTs of
`{ id, status, blocking }` still work and go stale after 5 seconds.

Hook-backed instances are refreshed on every `snapshot()`, so an idle Claude
session does not vanish after 5 seconds of silence. `SessionEnd` (or an
empty map after prune) removes the instance.

`snapshot()`:

1. Rebuilds `desktop` / `cli` from the hook map (timestamp = now).
2. Drops any non-hook instance with no POST for 5 seconds.
3. Prefixes each session id with `"{desktop|cli}:"` so the two sources
   cannot collide.
4. Unions `blocking` the same way.
5. Calls `summarize(status_by_id, blocking)`.

Desktop ASK 1 plus CLI RUN 1 is ASK 1 on the badge (ask wins), with
`ask=1 run=1 idle=0` in the CLI line.

## `summarize`

Same function as OpenCode. A session in `blocking` is ASK, even if `status`
still says `busy`. The same session is not also counted as RUN.

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
| else | `idle` | `idle` (0 if the map is empty) |

The clock omits a displayed 0 and caps at `9+`. The CLI still prints the
three raw totals: `claude RUN 1 (ask=0 run=1 idle=1)`.
