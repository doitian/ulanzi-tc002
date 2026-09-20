# Agent monitoring

`tc002 watch agents` mirrors agent-berth state on the clock. agent-berth owns
provider hooks, session tracking, and pruning; tc002 only reads its snapshots
and renders badges.

## Pipeline

1. `agent-berth setup` installs provider hooks. Hooks report session events to
   the agent-berth server, which applies the shared session transitions.
2. `tc002 watch agents` polls `agent-berth list --json` every `--interval`
   seconds and groups the returned sessions by provider.
3. Each provider with a reported session gets a display app named after it.
   The `agents` app always shows the summed counts.

Watch mode does not install hooks and does not run a bridge. agent-berth is the
only writer; tc002 is a read-only display client.

## Session mapping

| agent-berth status | Meaning | Clock badge |
| --- | --- | --- |
| `idle` | Discovered presence without a running turn | IDLE |
| `working` | Running a turn or known background work | RUN |
| `waiting` | Permission, question, or elicitation needs input | ASK |
| `done` | The tracked turn finished | IDLE |

Providers are `opencode`, `claude`, `codex`, `grok`, and `pi`. Sessions for any
other provider are skipped with a diagnostic. An unrecognized status is a
malformed response and stops the watcher.

## Badge counts

Waiting sessions count as ASK. Working sessions count as RUN. Idle and done
sessions count as IDLE. Each display shows the status with the highest
priority (**ASK > RUN > IDLE**) and the number of sessions in that status.

The `agents` app sums the provider counts and applies the same priority; it
shows IDLE without a number when nothing is reported. The clock caps numbers at
`9+`, while terminal output prints all three raw counts.

## Failures

A missing `agent-berth` executable, a five-second timeout, a nonzero exit, an
invalid JSON payload, or an API error stops the watcher and removes its display
apps. Ctrl-C and SIGTERM do the same.
