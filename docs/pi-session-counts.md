# Pi session counts

`tc002 watch agents --providers pi` shows one status and one number on
the clock. That number is not "how many chats exist". It is an aggregate of
sessions that this process has seen go ASK or RUN, across every Pi instance
that is still posting to the local bridge.

## Pipeline

```
Pi events  →  extension (per process)  →  POST /providers/pi
                                                    ↓
clock badge  ←  summarize()  ←  BridgeStore.snapshot()
```

1. `watch agents` starts a bridge (default `http://127.0.0.1:8009`) and
   installs `~/.pi/agent/extensions/tc002-watch.ts` with that URL.
2. Each Pi process loads the extension and POSTs once a second:
   `{ id: "<pid>", status: { <session>: "busy"|"idle" }, blocking: [<session>] }`.
3. The bridge keeps one record per `(provider, pid)`.
4. `snapshot("pi")` merges those records, then `summarize()` picks
   the badge kind and the displayed count.

Restart both `tc002 watch agents` and Pi after changing the extension.
Already-open Pi sessions pick up the file on `/reload`. If watch did not
exit cleanly, run `tc002 watch agents --teardown` to remove leftover
extensions and hooks.

`PI_CODING_AGENT_DIR` overrides the config directory (`~/.pi/agent`).

## What the extension reports

The extension does not list historical chats. A session enters `seen` only
when the agent starts, or when a UI prompt asks for input.

| Set | Meaning |
| --- | --- |
| `seen` | Sessions that already went ASK or RUN |
| `running` | Subset of `seen` whose agent is not settled |
| `pending` | Sessions blocked on `ui_prompt_start` |

Each flush sends `status[sid] = running ? "busy" : "idle"` for every `seen`
id, and `blocking` as the session ids in `pending`.

| Event | Effect |
| --- | --- |
| `agent_start` | add to `seen` and `running` |
| `agent_settled` | leave `running`, then prune |
| `ui_prompt_start` | add to `seen` and `pending` (ASK) |
| `ui_prompt_end` | leave `pending` |
| `session_start` (`new` / `resume` / `fork`) | prune idle leftovers |
| `session_start` while not idle | restore `running` (reload mid-turn) |
| `session_shutdown` | stop the heartbeat |

`retry` is not a Pi extension status. `summarize()` still treats `busy` and
`retry` as running if a direct POST ever sends `retry`.

Pi has no built-in subagents. Child sessions are not tracked.

### Idle chats

Shared rules: [idle-chats.md](idle-chats.md). The extension prunes idle
sessions in this process when:

- `/new`, `/resume`, or `/fork` starts a session (`session_start`)
- a session already in `seen` settles (`agent_settled`)

`/new`, `/resume`, and `/fork` rebind the extension, so the new instance
starts empty. A brand-new chat is not counted until ASK or RUN. UI prompts
add the session even when the agent is idle.

## Bridge merge

`BridgeStore` keys instances by `(provider, id)` where `id` is the Pi
pid. A later POST from the same pid replaces the previous payload.

`snapshot()`:

1. Drops any instance with no POST for 5 seconds (process quit).
2. Prefixes each session id with `"{pid}:"` so two processes cannot collide.
3. Unions `blocking` the same way.
4. Calls `summarize(status_by_id, blocking)`.

Several Pi terminals therefore add. Two pids each with one busy session
are RUN 2.

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
| else | `idle` | `idle` (0 if `seen` is empty) |

The clock omits a displayed 0 and caps at `9+`. The CLI still prints the
three raw totals: `pi RUN 1 (ask=0 run=1 idle=1)`.
