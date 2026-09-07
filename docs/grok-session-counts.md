# Grok session counts

`tc002 watch agents --providers grok` shows one status and one number on
the clock. That number is not "how many chats exist". It is an aggregate of
Grok CLI sessions that have gone ASK or RUN, as long as they are still live
in the local bridge.

## Pipeline

```
CLI command hook  →  POST /providers/grok  (hookEventName)
                                        ↓
clock badge  ←  summarize()  ←  BridgeStore.snapshot()
```

1. `watch agents` starts a bridge (default `http://127.0.0.1:8009`) and
   writes `~/.grok/hooks/tc002-watch.py` plus `tc002-watch.json` that
   POSTs stdin JSON to that URL.
2. The Grok CLI runs the command hook; the script POSTs each event to
   `/providers/grok`. Native Grok HTTP hooks cannot target loopback
   (SSRF protection), so this uses a command hook like Codex.
3. The bridge keeps hook-tracked sessions in one map, then posts one
   instance record: `cli`.
4. `snapshot("grok")` merges that record, then `summarize()` picks the
   badge kind and the displayed count.

Restart `tc002 watch agents` after changing hooks. If watch did not exit
cleanly, run `tc002 watch agents --teardown` to remove leftover hooks.
Reload hooks in an already-open Grok session (`/hooks`, then `r`) or
start a new session.

## What the hooks report

Hooks do not list historical chats. A session enters the map only when it
becomes busy, or when a permission prompt asks for input.

| Event | Effect |
| --- | --- |
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse` | `status = busy`, clear blocking |
| `Notification` of `permission_prompt` | blocking (ASK) |
| `Stop`, `StopFailure`, `StopCancelled` | `status = idle`, then prune |
| `Notification` of `idle_prompt` | `status = idle` if already tracked, then prune |
| `SessionStart` | prune only; the new chat is not counted until ASK or RUN |
| `SubagentStop` or any event with `subagentType` | ignored |
| `SessionEnd` | drop |

Grok sends camelCase envelopes (`hookEventName`, `sessionId`). Event values
may be snake_case (`pre_tool_use`); they are normalized to the names above.
`retry` is not a Grok hook status. `summarize()` still treats `busy` and
`retry` as running if a direct POST ever sends `retry`.

A payload with `subagentType` is ignored. Grok subagents have their own
session ids; counting them would show RUN 2 for one chat. A blocking
subagent keeps the parent busy until the parent turn ends. A background
subagent outlives that turn and must not hold the badge busy.

`watch agents` polls `~/.grok/active_sessions.json` and drops ids that are
not in it, so a missed `SessionEnd` or a stray POST cannot stick as a
second running session. A missing or unreadable file leaves the map
unchanged.

### Idle chats

Shared rules: [idle-chats.md](idle-chats.md). `prune(keep)` drops idle
sessions when:

- a session starts (`SessionStart`)
- the user submits a prompt (`UserPromptSubmit`)
- a session already in the map goes idle (`Stop`, `StopFailure`,
  `StopCancelled`, or `idle_prompt`)

`/new`, `/resume`, or a new CLI session only switches focus. Permission
prompts add the session even when that chat is not focused.

## Bridge merge

`BridgeStore` keys instances by `(provider, id)`. For Grok the id is `cli`,
rebuilt on every hook. Direct POSTs of `{ id, status, blocking }` still
work and go stale after 5 seconds.

Hook-backed instances are refreshed on every `snapshot()`, so an idle Grok
session does not vanish after 5 seconds of silence. `SessionEnd` (or an
empty map after prune) removes the instance.

`snapshot()`:

1. Rebuilds `cli` from the hook map (timestamp = now).
2. Drops any non-hook instance with no POST for 5 seconds.
3. Prefixes each session id with `"cli:"`.
4. Unions `blocking` the same way.
5. Calls `summarize(status_by_id, blocking)`.

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
three raw totals: `grok RUN 1 (ask=0 run=1 idle=1)`.
