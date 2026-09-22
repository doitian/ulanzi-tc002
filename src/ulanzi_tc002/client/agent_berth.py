import json
import subprocess

from ulanzi_tc002.client.agent_status import summarize_counts

COMMAND_TIMEOUT = 5
KNOWN_PROVIDERS = ("opencode", "claude", "codex", "grok", "pi")
COUNT_KEYS = ("waiting", "running", "done", "idle")


def parse_stats(payload):
    if not isinstance(payload, list):
        raise ValueError("Invalid agent-berth response: expected a JSON array")
    by_provider = {}
    messages = []
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("Invalid agent-berth response: expected a provider stats object")
        provider = row.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("Invalid agent-berth response: expected a provider name")
        counts = {key: row.get(key) for key in COUNT_KEYS}
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
               for value in counts.values()):
            raise ValueError(f"Invalid agent-berth counts for provider {provider}: {counts!r}")
        provider = provider.lower()
        if provider not in KNOWN_PROVIDERS:
            messages.append(f"Skipping agent-berth provider {provider}: no matching tc002 provider app.")
            continue
        if any(counts.values()):
            by_provider[provider] = counts
    states = [(name, *summarize_counts(by_provider[name])) for name in KNOWN_PROVIDERS if name in by_provider]
    return states, tuple(dict.fromkeys(messages))


def read_stats():
    command = ["agent-berth", "stats", "--json"]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=COMMAND_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        raise ValueError("agent-berth was not found on PATH; install agent-berth to use 'tc002 watch agents'") from None
    except subprocess.TimeoutExpired:
        raise ValueError(f"agent-berth stats timed out after {COMMAND_TIMEOUT} seconds") from None
    if result.returncode:
        reason = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise ValueError(f"Unable to read agent-berth stats: {reason}")
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise ValueError("Invalid JSON from agent-berth stats --json") from None
    return parse_stats(payload)
