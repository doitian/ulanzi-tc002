import time
import unittest

from ulanzi_tc002.client import claude, codex, grok
from ulanzi_tc002.client.agent_status import (
    AgentEvent, AgentEventKind, AgentSession, AgentStatus, apply_event,
)
from ulanzi_tc002.client.bridge import BridgeStore


class AgentStatusTests(unittest.TestCase):
    def test_turn_waits_resumes_and_ignores_late_tool_events(self):
        for provider in (claude, codex, grok):
            with self.subTest(provider=provider.__name__):
                sessions = {}

                def emit(name):
                    provider.apply_hook(sessions, {
                        "session_id": "s", "hook_event_name": name,
                    }, set())

                emit("SessionStart")
                emit("PostToolUse")
                self.assertEqual(sessions, {})
                emit("UserPromptSubmit")
                emit("PermissionRequest")
                emit("PreToolUse")
                self.assertEqual(sessions["s"].status, AgentStatus.WAITING)
                emit("PostToolUse")
                self.assertEqual(sessions["s"].status, AgentStatus.WORKING)
                emit("Stop")
                emit("PostToolUse")
                emit("PreToolUse")
                emit("Stop")
                self.assertEqual(sessions["s"].status, AgentStatus.DONE)
                emit("UserPromptSubmit")
                self.assertEqual(sessions["s"].status, AgentStatus.WORKING)
                emit("SessionEnd")
                emit("PostToolUse")
                self.assertEqual(sessions, {})

    def test_notifications_do_not_revive_finished_turns(self):
        sessions = {}
        for kind in (AgentEventKind.PROMPT_SUBMIT, AgentEventKind.NOTIFICATION):
            apply_event(sessions, AgentEvent("s", kind))
        self.assertEqual(sessions["s"].status, AgentStatus.WAITING)
        for kind in (AgentEventKind.STOP, AgentEventKind.NOTIFICATION):
            apply_event(sessions, AgentEvent("s", kind))
        self.assertEqual(sessions["s"].status, AgentStatus.DONE)
        apply_event(sessions, AgentEvent("s", AgentEventKind.QUESTION_ASKED))
        self.assertEqual(sessions["s"].status, AgentStatus.WAITING)

    def test_parent_and_child_with_same_session_id_are_independent(self):
        for provider in (claude, codex):
            with self.subTest(provider=provider.__name__):
                sessions = {}

                def emit(name, **extra):
                    provider.apply_hook(sessions, {
                        "session_id": "parent", "hook_event_name": name, **extra,
                    }, set())

                emit("UserPromptSubmit")
                emit("PermissionRequest", agent_id="child")
                self.assertEqual(sessions["parent"].status, AgentStatus.WORKING)
                self.assertEqual(sessions["parent:child"].status, AgentStatus.WAITING)
                emit("Stop", agent_id="child")
                self.assertEqual(set(sessions), {"parent"})
                emit("UserPromptSubmit", agent_id="child")
                emit("SessionEnd")
                self.assertEqual(sessions, {})

    def test_idle_pruning_is_scoped_to_source_and_process(self):
        sessions = {}
        for sid, source, pid in (("first", "cli", 1), ("second", "cli", 2),
                                 ("desktop", "desktop", 1)):
            apply_event(sessions, AgentEvent(sid, AgentEventKind.PROMPT_SUBMIT, source, pid))
            apply_event(sessions, AgentEvent(sid, AgentEventKind.STOP, source, pid))
        apply_event(sessions, AgentEvent("new", AgentEventKind.SESSION_START, pid=1))
        self.assertEqual(set(sessions), {"second", "desktop"})
        apply_event(sessions, AgentEvent("second", AgentEventKind.PROMPT_SUBMIT))
        apply_event(sessions, AgentEvent("second", AgentEventKind.STOP))
        self.assertEqual(sessions["second"].pid, 2)
        self.assertEqual(sessions["second"].status, AgentStatus.DONE)

    def test_child_stop_without_identity_does_not_end_parent(self):
        sessions = {}
        for name in ("UserPromptSubmit", "SubagentStop"):
            codex.apply_hook(sessions, {"session_id": "s", "hook_event_name": name}, set())
        self.assertEqual(sessions["s"].status, AgentStatus.WORKING)

    def test_child_without_parent_identity_is_removed_when_done(self):
        for provider in (claude, codex):
            with self.subTest(provider=provider.__name__):
                sessions = {}
                for name in ("UserPromptSubmit", "Stop"):
                    provider.apply_hook(sessions, {"agent_id": "child", "hook_event_name": name}, set())
                self.assertEqual(sessions, {})

    def test_grok_elicitation_is_waiting(self):
        sessions = {}
        grok.apply_hook(sessions, {
            "sessionId": "s", "hookEventName": "notification",
            "notificationType": "elicitation_dialog",
        })
        self.assertEqual(sessions["s"].status, AgentStatus.WAITING)

    def test_finished_discovered_process_is_removed(self):
        for state in ("done", "failed", "stopped"):
            with self.subTest(state=state):
                sessions = {"s": AgentSession(status=AgentStatus.WORKING)}
                claude.apply_agents(sessions, [{"sessionId": "s", "state": state}])
                self.assertEqual(sessions, {})


class AgentStoreTests(unittest.TestCase):
    def test_heartbeat_cannot_overwrite_or_refresh_hook_state(self):
        store = BridgeStore(desktop_ids=set())
        store.update("codex", {"session_id": "s", "hook_event_name": "PermissionRequest"})
        store.update("codex", {"id": "cli", "status": {"s": "busy"}})
        self.assertEqual(store.snapshot("codex"), ("ask", 1, {"ask": 1, "run": 1, "idle": 0}))
        self.assertEqual(store.snapshot("codex", now=time.time() + 60),
                         ("ask", 1, {"ask": 1, "run": 0, "idle": 0}))
        store.update("codex", {"session_id": "s", "hook_event_name": "SessionEnd"})
        self.assertEqual(store.snapshot("codex")[:2], ("idle", 0))

    def test_report_identifiers_containing_colons_do_not_collide(self):
        store = BridgeStore()
        store.update("opencode", {"id": "a:b", "status": {"c": "busy"}})
        store.update("opencode", {"id": "a", "status": {"b:c": "idle"}, "blocking": ["b:c"]})
        self.assertEqual(store.snapshot("opencode"), ("ask", 1, {"ask": 1, "run": 1, "idle": 0}))

    def test_all_provider_transports_use_the_same_badge_priority(self):
        store = BridgeStore(desktop_ids=set())
        for provider in ("claude", "codex", "grok"):
            for sid, name in (("run", "UserPromptSubmit"), ("done", "UserPromptSubmit"),
                              ("done", "Stop"), ("ask", "PermissionRequest")):
                store.update(provider, {"session_id": sid, "hook_event_name": name})
        for provider in ("opencode", "pi"):
            store.update(provider, {
                "id": "process", "status": {"run": "busy", "done": "idle", "ask": "busy"},
                "blocking": ["ask"],
            })
        for provider in ("claude", "codex", "grok", "opencode", "pi"):
            with self.subTest(provider=provider):
                self.assertEqual(store.snapshot(provider),
                                 ("ask", 1, {"ask": 1, "run": 1, "idle": 1}))
                store.clear(provider)
                self.assertEqual(store.snapshot(provider)[:2], ("idle", 0))

    def test_discovery_cannot_be_applied_to_the_wrong_provider(self):
        store = BridgeStore()
        with self.assertRaisesRegex(ValueError, "does not support agent discovery"):
            store.merge_agents("codex", [{"sessionId": "s", "state": "working"}])
        self.assertEqual(store.hooks, {})


if __name__ == "__main__":
    unittest.main()
