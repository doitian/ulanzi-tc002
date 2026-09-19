# Monitor tty7

`tc002 watch tty7` reads an existing tty7 server, groups its pane statuses by
agent, and sends provider badges to the TC002 server. It uses the same app
names and icons as `tc002 watch agents`. The standalone command keeps its own
provider hooks and session tracking; tty7 mode takes snapshots from tty7.

## Setup and commands

The `tty7` executable must be on PATH and its server must already be running.
Run `tty7 doctor` to check connectivity and hook installation. Enable or update
status hooks in tty7 Settings > Agents for the agents you want to monitor.

```powershell
tc002 watch tty7
tc002 watch tty7 --interval 2
tc002 watch tty7 --machine devbox
tc002 watch tty7 --once
```

| Option | Meaning |
| --- | --- |
| `--interval SECONDS` | Delay between polls; default 1, must be positive and finite |
| `--machine MACHINE` | Forward to tty7's existing linked machine; default is the local server |
| `--once` | Read one snapshot, send its badges, then exit and remove the display apps |

The usual global TC002 endpoint options still apply, for example
`tc002 --host clock-server watch tty7`. tty7 inherits `TTY7_CONFIG_DIR` from
the environment. Remote monitoring uses an already connected tty7 machine;
this command does not establish a connection or start a tty7 server.

The watcher does not read stdin or accept the standalone watcher's `a`/`r`
commands. Ctrl-C or SIGTERM exits and removes its display apps. A polling
or display-update error also runs cleanup. No provider hooks or plugins are
installed or removed by this mode. All watch modes share app names, so use
one mode at a time for a given provider on the same TC002 server.

## Status and counts

Each poll invokes `tty7 agents --json`, with `--machine` when supplied.
The first poll runs immediately. After processing each snapshot and sending
changed badges to the TC002 server, the watcher waits `--interval` seconds
(default 1) before running the command again. Each command has a five-second
timeout. The adapter reads tty7's
[pane-state JSON](https://github.com/l0ng-ai/tty7/blob/d07850a98e184d3b0c85cce4e728a21e8f1b7212/crates/tty7-core/src/daemon/control.rs#L327):

```json
{
  "agents": [
    {
      "pane_id": 42,
      "agent": "Codex",
      "state": {"status": "working", "session_id": "session-1"}
    }
  ]
}
```

The count is per reported pane, not per chat or subagent. Panes sharing a
session id still count separately. Agent names select the existing provider
app, case-insensitively:

| tty7 agent | TC002 app |
| --- | --- |
| `OpenCode` | `opencode` |
| `Claude` | `claude` |
| `Codex` | `codex` |
| `Grok` | `grok` |
| `Pi` | `pi` |

Unmapped or unnamed agents are skipped with a diagnostic. They do not create
new app names or contribute to the summary. Every snapshot replaces the
previous one; a pane disappears from the count when tty7 stops reporting it.
Provider apps are created when first reported and removed when their last
pane disappears. The `agents` summary app remains present for the entire
watch, including when only one provider or no providers are reported.

| tty7 state | TC002 count |
| --- | --- |
| `waiting` | ASK |
| `working` | RUN |
| `idle`, `done` | IDLE |

The [shared badge priority](agent-monitoring.md#badge-counts) is ASK > RUN >
IDLE. Two working Codex panes produce `codex RUN 2` and `agents RUN 2`, even
without another provider. Adding one waiting Claude pane produces
`claude ASK 1` and changes the summary to
`agents ASK 1 (ask=1 run=2 idle=0)`. Each provider uses its usual icon, and
the summary uses the usual terminal icon.

When no supported providers are reported, the provider apps are removed and
the `agents` summary shows IDLE without a number (all counts are zero). The
terminal prints `No supported agents reported by tty7`. Display updates are
sent only when a provider's or summary's counts change.

## Diagnostics and failures

tty7 may report agents with missing or outdated hooks in a separate
`diagnostics` array. Those diagnostics appear on stderr when they change;
they are not counted as idle agent panes. Install or update the indicated hooks
in tty7. The clock can only show the panes that tty7 actually reports.

A missing executable, nonzero exit, five-second command timeout, malformed
JSON, or unknown status stops the watcher with an error. These failures do not
produce an empty or idle snapshot. The first read happens before creating
display apps; a failure after startup removes those apps. Restart the command
after restoring tty7 connectivity.
