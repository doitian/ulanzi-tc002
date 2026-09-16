# Agent monitoring

`tc002 watch agents` uses provider adapters, shared session state, and a
separate display summary. The design follows tty7's
[agent state machine](https://github.com/l0ng-ai/tty7/blob/d07850a98e184d3b0c85cce4e728a21e8f1b7212/crates/tty7-core/src/core/cli_agent.rs#L691)
and [hook adapters](https://github.com/l0ng-ai/tty7/blob/d07850a98e184d3b0c85cce4e728a21e8f1b7212/crates/tty7-core/src/core/agent_hooks.rs).
tc002 uses its local HTTP bridge because it does not own the agents' terminals.
There is no tty7 runtime dependency.

To read an existing tty7 server directly, use the separate
[`tc002 watch tty7`](tty7-status.md) command. It converts tty7 pane snapshots
into the same badge counts without using the standalone hook bridge.

## State and events

`client/agent_status.py` defines the normalized events, session state,
pruning rules, and badge aggregation. Claude, Codex, and Grok translate their
hook payloads into `AgentEvent` records and apply the same transitions.
OpenCode and Pi send complete process snapshots using their existing plugin
protocol; these feed the same badge aggregation.

| Internal state | Meaning | Clock badge |
| --- | --- | --- |
| `idle` | Discovered presence without a running turn | IDLE |
| `working` | Running a turn or known background work | RUN |
| `waiting` | Permission, question, or elicitation needs input | ASK |
| `done` | The tracked turn finished | IDLE |

| Normalized event | Effect |
| --- | --- |
| `session-start` | Prune inactive chats in the same source/process; do not count a new empty chat |
| `prompt-submit` | Start or resume working; clear a wait |
| `tool-start` | Discover a running session if unseen; preserve waiting and done states |
| `tool-complete` | Resume a waiting session; preserve working, idle, and done states |
| `permission-request`, `question-asked` | Enter waiting, even if the session was not already tracked |
| `notification` | Enter waiting only from working |
| `stop` | Mark a tracked turn done, or keep it working if Claude reports background work |
| `session-end` | Remove the session and its tracked children |

Adapters recognize blocking notification types and translate them into an
explicit permission request. Unknown hook events and unrelated notifications
do not create sessions. A late `PostToolUse` cannot recreate a removed session
or change a completed turn to RUN. A new `UserPromptSubmit` starts the next turn.

tc002 retains its [session-count policy](idle-chats.md): a new empty chat is
not counted, active work survives focus changes, and completed child sessions
are removed. Unlike tty7's per-pane status, tc002 aggregates concurrent sessions.
Claude's discovery poll can also include an idle process before its first hook.

## Bridge storage

`BridgeStore` keeps two independent collections:

- Hook sessions hold `AgentSession` objects until a lifecycle event, pruning,
  or provider discovery removes them. Silence alone does not expire them.
- Plugin snapshots hold `{ id, status, blocking }` reports. Each new report
  replaces that provider/instance's previous report. They expire after five
  seconds without a heartbeat.

A snapshot reads hook state directly, expires stale plugin reports, and
aggregates both. It does not manufacture plugin reports or refresh timestamps
for hook sessions. Hook identities and plugin identities use separate tuple
keys, so a report named `cli` cannot overwrite hook state and colons inside
identifiers cannot merge unrelated sessions.

## Badge counts

Waiting sessions count as ASK. Working sessions and plugin `busy`/`retry`
statuses count as RUN. Idle/done sessions and plugin `idle` statuses count as
IDLE. A session in a plugin's `blocking` list counts only as ASK, even if its
status says busy. Multiple blocking requests for one session count once.

The displayed status follows **ASK > RUN > IDLE**; the displayed number is
the count for that status. An empty store shows IDLE without a number. The
clock caps numbers at `9+`, while terminal output prints all three raw counts.
The `agents` app sums those counts and applies the same priority. Standalone
`watch agents` shows this summary with multiple providers active;
`watch tty7` always shows it, including with one or no providers.

## Provider lifecycle

Providers share hook/plugin installation, optional polling, and teardown.
Claude polls `claude agents --json`; Grok polls its active-session file.
The other providers report through hooks or plugin heartbeats. Removing a
provider stops its poller, removes its configuration and display app, rejects
further reports, and clears its state. Adding it again starts empty.

Provider details:

- [Claude](claude-session-counts.md)
- [Codex](codex-session-counts.md)
- [Grok](grok-session-counts.md)
- [OpenCode](opencode-session-counts.md)
- [Pi](pi-session-counts.md)
