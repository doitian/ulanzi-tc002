# Agent monitoring

`tc002 watch agents` mirrors agent-berth state on the clock. agent-berth owns
provider hooks, session tracking, and pruning; tc002 only reads its snapshots
and renders badges.

## Pipeline

1. `agent-berth setup` installs provider hooks. Hooks report session events to
   the agent-berth server, which applies the shared session transitions.
2. `tc002 watch agents` polls `agent-berth stats --json` every `--interval`
   seconds and reads the per-provider status counts.
3. Each provider with reported sessions gets a display app named after it.
   The `agents` app always shows the summed counts.

Watch mode does not install hooks and does not run a bridge. agent-berth is the
only writer; tc002 is a read-only display client.

## Session mapping

| agent-berth status | Meaning | Clock badge |
| --- | --- | --- |
| `idle` | Discovered presence without a running turn | IDLE |
| `running` | Running a turn or known background work | RUNNING |
| `waiting` | Permission, question, or elicitation needs input | WAITING |
| `done` | The tracked turn finished | DONE |

Providers are `opencode`, `claude`, `codex`, `grok`, and `pi`. Counts for any
other provider are skipped with a diagnostic, and providers with no sessions
are dropped. A missing, negative, or non-integer count is a malformed response
and is retried like any other agent-berth failure.

## Badge counts

Each display shows the status with
the highest priority (**WAITING > RUNNING > DONE > IDLE**) and the number of sessions in
that status.

The `agents` app sums the provider counts and applies the same priority; it
shows IDLE without a number when nothing is reported. The clock caps numbers at
`9+`, while terminal output prints all four raw counts.

## Failures

A missing `agent-berth` executable, a five-second timeout, a nonzero exit, or
an invalid JSON payload prints an error on stderr and is retried with
exponential backoff: the wait doubles from `--interval` up to a maximum of
five minutes and resets after a successful read. Display apps and their last
badges are kept during the outage. `--once` has nothing to retry, so it exits
with the error instead. An API error, Ctrl-C, or SIGTERM stops the watcher and
removes its display apps.
