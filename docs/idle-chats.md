# Idle chats

The clock count is not "how many chats exist". Switching to a new chat must
not stack idle leftovers. These rules are shared by OpenCode, Claude, Codex,
and Grok.

A session is tracked only after it has gone ASK or RUN. Historical chats and
a brand-new empty chat are not counted.

## Keep

- Running sessions (busy / retry)
- Pending sessions (permission, question, elicitation)
- At most one idle top-level session in the same process or source

Those still count after `/new`, `/sessions`, `/clear`, `/resume`, or a new
Desktop session. Focus change does not delete the old chat. If it is still
running, or later asks for input, it stays in the report even when it is not
focused.

## Drop

Idle sessions that are not the one being kept, not running, and not pending.
Prune on focus change and when a tracked top-level session goes idle.

After pruning, the report is: every running or asking session, plus at most
one idle top-level chat.

## Children

OpenCode, Claude, and Codex count subagent sessions while they run or ask.
They are dropped as soon as they go idle. They never become the idle
representative. Grok ignores child events; see
[grok-session-counts.md](grok-session-counts.md).

## Per provider

When each event prunes, and what "process or source" means, is in
[opencode-session-counts.md](opencode-session-counts.md),
[claude-session-counts.md](claude-session-counts.md),
[codex-session-counts.md](codex-session-counts.md), and
[grok-session-counts.md](grok-session-counts.md).
