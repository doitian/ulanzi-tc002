import json
import subprocess

from ulanzi_tc002.client.agent_status import AgentStatus, summarize

COMMAND_TIMEOUT = 5
KNOWN_PROVIDERS = ("opencode", "claude", "codex", "grok", "pi")
KNOWN_STATUSES = {
    AgentStatus.IDLE,
    AgentStatus.RUNNING,
    AgentStatus.WAITING,
    AgentStatus.DONE,
}


def parse_list(payload):
    if not isinstance(payload, list):
        raise ValueError("Invalid agent-berth response: expected a JSON array")
    grouped = {}
    messages = []
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("Invalid agent-berth response: expected a session object")
        provider = row.get("provider")
        session_id = row.get("session_id")
        status = row.get("status")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("Invalid agent-berth response: expected a provider name")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("Invalid agent-berth response: expected a session_id")
        if status not in KNOWN_STATUSES:
            raise ValueError(f"Invalid agent-berth status for session {session_id}: {status!r}")
        provider = provider.lower()
        if provider not in KNOWN_PROVIDERS:
            messages.append(f"Skipping agent-berth provider {provider}: no matching tc002 provider app.")
            continue
        grouped.setdefault(provider, {})[session_id] = status
    states = [(name, *summarize(grouped[name], ())) for name in KNOWN_PROVIDERS if name in grouped]
    return states, tuple(dict.fromkeys(messages))


def read_list():
    command = ["agent-berth", "list", "--json"]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=COMMAND_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        raise ValueError("agent-berth was not found on PATH; install agent-berth to use 'tc002 watch agents'") from None
    except subprocess.TimeoutExpired:
        raise ValueError(f"agent-berth list timed out after {COMMAND_TIMEOUT} seconds") from None
    if result.returncode:
        reason = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise ValueError(f"Unable to read agent-berth sessions: {reason}")
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise ValueError("Invalid JSON from agent-berth list --json") from None
    return parse_list(payload)
