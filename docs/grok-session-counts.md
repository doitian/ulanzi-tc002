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
3. The adapter normalizes Grok field names and translates hooks into shared
   `AgentEvent` records. The bridge retains each `AgentSession` with source `cli`.
4. `snapshot("grok")` reads those sessions and any plugin reports, then
   the shared `summarize()` picks the badge kind and displayed count.

Restart `tc002 watch agents` after changing hooks. If watch did not exit
cleanly, run `tc002 watch agents --teardown` to remove leftover hooks.
Reload hooks in an already-open Grok session (`/hooks`, then `r`) or
start a new session.

## What the hooks report

Hooks do not list historical chats. A session enters the map only when it
becomes busy, or when a permission prompt asks for input.

| Event | Effect |
| --- | --- |
| `UserPromptSubmit` | working (RUN), clear waiting |
| `PreToolUse` | discover working activity if unseen; preserve waiting and done |
| `PostToolUse` | resume waiting activity; never create a session or revive a done turn |
| `Notification` of `permission_prompt` or `elicitation_dialog`, or a direct `PermissionRequest` | waiting (ASK) |
| `Stop`, `StopFailure`, `StopCancelled` | done (IDLE), then prune |
| `Notification` of `idle_prompt` | done (IDLE) if already tracked, then prune |
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

## Bridge merge and badge counts

`BridgeStore` stores Grok hook sessions separately from plugin
heartbeats. Hook state is read directly during `snapshot()` and does not
expire after five seconds of silence. Lifecycle events, idle pruning, and
provider discovery govern its lifetime. Direct POSTs of
`{ id, status, blocking }` remain supported and expire after five seconds
without a report.

The [shared monitor](agent-monitoring.md#badge-counts) maps waiting to ASK,
working to RUN, and idle/done to IDLE. ASK wins over RUN, which wins over IDLE;
a waiting session is never counted again as running. Hook and plugin identities
are kept separate, including reports whose instance id is `cli` or `desktop`.
