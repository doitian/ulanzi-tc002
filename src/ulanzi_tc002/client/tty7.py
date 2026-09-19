import json
import subprocess

from ulanzi_tc002.client.agent_status import AgentStatus, summarize
from ulanzi_tc002.client.watch import KNOWN_PROVIDERS, watch_status

COMMAND_TIMEOUT = 5


def parse_status(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("agents"), list):
        raise ValueError("Invalid tty7 response: expected an agents array")
    statuses = {}
    for row in payload["agents"]:
        if not isinstance(row, dict):
            raise ValueError("Invalid tty7 response: expected an agent object")
        pane = row.get("pane_id")
        state = row.get("state")
        if type(pane) is not int or pane < 0 or not isinstance(state, dict):
            raise ValueError("Invalid tty7 response: expected pane_id and state")
        agent = row.get("agent")
        if agent is not None and not isinstance(agent, str):
            raise ValueError("Invalid tty7 response: expected an agent name")
        try:
            statuses[pane] = (agent.lower() if agent else None, AgentStatus(state.get("status")))
        except ValueError:
            raise ValueError(f"Invalid tty7 status for pane {pane}: {state.get('status')!r}") from None
    diagnostics = payload.get("diagnostics", [])
    if not isinstance(diagnostics, list) or any(not isinstance(item, dict) for item in diagnostics):
        raise ValueError("Invalid tty7 response: expected a diagnostics array of objects")
    messages = []
    for item in diagnostics:
        if item.get("kind") == "agent_status_hooks_unavailable":
            agent = item.get("agent", "agent")
            state = str(item.get("hooks_state", "unavailable")).replace("_", " ")
            action = item.get("action", "install")
            messages.append(f"{agent}: tty7 status hooks are {state}; {action} them in tty7 Settings > Agents.")
        else:
            messages.append(json.dumps(item, sort_keys=True))
    grouped = {}
    for pane, (agent, status) in statuses.items():
        if agent not in KNOWN_PROVIDERS:
            messages.append(f"Skipping tty7 agent {agent or '(unnamed)'}: no matching tc002 provider app.")
            continue
        grouped.setdefault(agent, {})[pane] = status
    states = [(name, *summarize(grouped[name], ())) for name in KNOWN_PROVIDERS if name in grouped]
    return states, tuple(dict.fromkeys(messages))


def read_status(machine=None):
    command = ["tty7", "agents", "--json"]
    if machine is not None:
        command.extend(["--machine", machine])
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=COMMAND_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        raise ValueError("tty7 was not found on PATH; install tty7 to use 'tc002 watch tty7'") from None
    except subprocess.TimeoutExpired:
        raise ValueError(f"tty7 agents timed out after {COMMAND_TIMEOUT} seconds") from None
    if result.returncode:
        reason = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise ValueError(f"Unable to read tty7 agents: {reason}")
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise ValueError("Invalid JSON from tty7 agents --json") from None
    return parse_status(payload)


def watch_tty7(args, api):
    watch_status(args, api, "tty7", lambda: read_status(args.machine))
