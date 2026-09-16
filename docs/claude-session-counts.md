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
4. The adapter translates hooks into shared `AgentEvent` records. The
   bridge retains each `AgentSession` with its `desktop` or `cli` source.
5. `snapshot("claude")` reads those sessions and any plugin reports, then
   the shared `summarize()` picks the badge kind and displayed count.

Restart `tc002 watch agents` after changing hooks. Already-open Claude
sessions pick up the hooks on their next event. If watch did not exit
cleanly, run `tc002 watch agents --teardown` to remove leftover hooks.

## What the hooks report

Hooks do not list historical chats. A session enters the map only when it
becomes busy, or when a permission / elicitation / notification asks for
input.

| Event | Effect |
| --- | --- |
| `UserPromptSubmit` | working (RUN), clear waiting |
| `PreToolUse` | discover working activity if unseen; preserve waiting and done |
| `PostToolUse` | resume waiting activity; never create a session or revive a done turn |
| `PermissionRequest`, `Elicitation` | blocking (ASK) |
| `Notification` of `permission_prompt`, `agent_needs_input`, `elicitation_dialog`, `elicitation_url_dialog` | blocking (ASK) |
| `Stop`, `StopFailure` | working if the payload reports running background tasks; otherwise done (IDLE), then prune |
| `SessionStart` | prune only; the new chat is not counted until ASK or RUN |
| `SessionEnd` | drop the session and its tracked children |

`retry` is not a Claude hook status. `summarize()` still treats `busy` and
`retry` as running if a direct plugin-style POST sends `retry`.

The [Stop hook's `background_tasks` array](https://code.claude.com/docs/en/hooks#stop-input)
keeps a session in RUN while a shell command, subagent, or other task is
running after the foreground response ends. Multiple tasks still count as
one session. A Stop event can discover such a session even if its earlier
hooks were missed. A subsequent Stop with no running tasks returns it to
IDLE; SessionEnd removes it. While the foreground turn is stopped, an explicit
`idle` report from `claude agents --json` also returns the session to IDLE.
This handles manually stopping the last background task without another Stop
hook, on the next successful poll (normally once per second). Busy polls keep
it running, and rows without a status do not clear activity. Rows explicitly
marked done, failed, or stopped remove that session and its children. A new
foreground prompt or tool event restores hook-based tracking. If Claude cannot report
the session's status, the bridge still needs a subsequent hook to clear RUN.
Scheduled `session_crons` alone do not count as
running work. Payloads without background task information retain the
previous idle behavior.

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
that chat is not focused. Subagent turns use `{session_id}:{agent_id}` so child
events cannot overwrite the parent. Ending a parent also removes its children. Sessions from
`claude agents --json` carry a `pid`; prune skips a different pid so a second
CLI terminal is not dropped when the first runs `/clear`.

## Bridge merge and badge counts

`BridgeStore` stores Claude hook sessions separately from plugin
heartbeats. Hook state is read directly during `snapshot()` and does not
expire after five seconds of silence. Lifecycle events, idle pruning, and
provider discovery govern its lifetime. Direct POSTs of
`{ id, status, blocking }` remain supported and expire after five seconds
without a report.

The [shared monitor](agent-monitoring.md#badge-counts) maps waiting to ASK,
working to RUN, and idle/done to IDLE. ASK wins over RUN, which wins over IDLE;
a waiting session is never counted again as running. Hook and plugin identities
are kept separate, including reports whose instance id is `cli` or `desktop`.
