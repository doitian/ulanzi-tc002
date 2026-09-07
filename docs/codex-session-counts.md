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
4. The bridge keeps hook-tracked sessions in one map, then posts two
   instance records: `desktop` and `cli`.
5. `snapshot("codex")` merges those records, then `summarize()` picks the
   badge kind and the displayed count.

Restart `tc002 watch agents` after changing hooks. If watch did not exit
cleanly, run `tc002 watch agents --teardown` to remove leftover hooks.
Codex may ask you to trust the new hook in `/hooks` before it will run.
Already-open Codex sessions pick up the hooks on their next event.

## What the hooks report

Hooks do not list historical chats. A session enters the map only when it
becomes busy, or when a permission request asks for input.

| Event | Effect |
| --- | --- |
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse` | `status = busy`, clear blocking |
| `PermissionRequest` | blocking (ASK) |
| `Stop`, `Interrupt` | `status = idle`, then prune |
| `SessionStart` | prune only; the new chat is not counted until ASK or RUN |
| `SubagentStop` | drop the child |
| `SessionEnd` | drop |

`retry` is not a Codex hook status. `summarize()` still treats `busy` and
`retry` as running if a direct POST ever sends `retry`.

Subagent turns use `agent_id` and are keyed as `{session_id}:{agent_id}` so
they do not overwrite the parent.

### Idle chats

Shared rules: [idle-chats.md](idle-chats.md). `prune(keep, source)` drops idle
sessions of that source when:

- a session starts (`SessionStart`: startup, resume, clear, compact)
- the user submits a prompt (`UserPromptSubmit`)
- a session already in the map goes idle (`Stop`, `Interrupt`)

A new Desktop session, `/clear`, `/resume`, or a new CLI session only
switches focus. Permission requests add the session even when that chat is
not focused. Child sessions are dropped as soon as they go idle.

## Bridge merge

`BridgeStore` keys instances by `(provider, id)`. For Codex the ids are
`desktop` and `cli`, rebuilt on every hook. Direct POSTs of
`{ id, status, blocking }` still work and go stale after 5 seconds.

Hook-backed instances are refreshed on every `snapshot()`, so an idle Codex
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
three raw totals: `codex RUN 1 (ask=0 run=1 idle=1)`.
