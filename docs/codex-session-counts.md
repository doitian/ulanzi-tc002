# Codex session counts

`tc002 watch agents --providers codex` shows one status and one number on
the clock. That number is not "how many chats exist". It is an aggregate of
Codex sessions that have gone ASK or RUN, from both the ChatGPT desktop app
and the CLI, as long as they are still live in the local bridge.

## Pipeline

```
Desktop + CLI hooks  →  command hook  →  POST /providers/codex
                                     ↓
clock badge  ←  summarize()  ←  BridgeStore.snapshot()
```

1. `watch agents` starts a bridge (default `http://127.0.0.1:8009`) and
   writes `~/.codex/hooks/tc002-watch.py` plus a matcher in
   `~/.codex/hooks.json` that POSTs stdin JSON to that URL.
2. Codex fires the same hooks in the CLI and the ChatGPT desktop app. Each
   event is POSTed to `/providers/codex`.
3. Desktop vs CLI is `originator` containing `desktop` (from the event or
   the transcript), else a match against Desktop session ids in
   `~/.codex/sessions`, else `cli`.
4. The adapter translates hooks into shared `AgentEvent` records. The
   bridge retains each `AgentSession` with its `desktop` or `cli` source.
5. `snapshot("codex")` reads those sessions and any plugin reports, then
   the shared `summarize()` picks the badge kind and displayed count.

Restart `tc002 watch agents` after changing hooks. If watch did not exit
cleanly, run `tc002 watch agents --teardown` to remove leftover hooks.
Codex may ask you to trust the new hook in `/hooks` before it will run.
Already-open Codex sessions pick up the hooks on their next event.

## What the hooks report

Hooks do not list historical chats. A session enters the map only when it
becomes busy, or when a permission request asks for input.

| Event | Effect |
| --- | --- |
| `UserPromptSubmit` | working (RUN), clear waiting |
| `PreToolUse` | discover working activity if unseen; preserve waiting and done |
| `PostToolUse` | resume waiting activity; never create a session or revive a done turn |
| `PermissionRequest` | blocking (ASK) |
| `Stop`, `Interrupt` | done (IDLE), then prune |
| `SessionStart` | prune only; the new chat is not counted until ASK or RUN |
| `SubagentStop` with `agent_id` | drop the child; events without a child identity leave the parent alone |
| `SessionEnd` | drop the session and its tracked children |

`retry` is not a Codex hook status. `summarize()` still treats `busy` and
`retry` as running if a direct POST ever sends `retry`.

Subagent turns use `agent_id` and are keyed as `{session_id}:{agent_id}` so
they do not overwrite the parent. Ending a parent also removes its children.

### Idle chats

Shared rules: [idle-chats.md](idle-chats.md). `prune(keep, source)` drops idle
sessions of that source when:

- a session starts (`SessionStart`: startup, resume, clear, compact)
- the user submits a prompt (`UserPromptSubmit`)
- a session already in the map goes idle (`Stop`, `Interrupt`)

A new Desktop session, `/clear`, `/resume`, or a new CLI session only
switches focus. Permission requests add the session even when that chat is
not focused. Child sessions are dropped as soon as they go idle.

## Bridge merge and badge counts

`BridgeStore` stores Codex hook sessions separately from plugin
heartbeats. Hook state is read directly during `snapshot()` and does not
expire after five seconds of silence. Lifecycle events, idle pruning, and
provider discovery govern its lifetime. Direct POSTs of
`{ id, status, blocking }` remain supported and expire after five seconds
without a report.

The [shared monitor](agent-monitoring.md#badge-counts) maps waiting to ASK,
working to RUN, and idle/done to IDLE. ASK wins over RUN, which wins over IDLE;
a waiting session is never counted again as running. Hook and plugin identities
are kept separate, including reports whose instance id is `cli` or `desktop`.
