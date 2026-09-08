import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ulanzi_tc002.client.bridge import Bridge, BridgeStore
from ulanzi_tc002.client.cli import main
from ulanzi_tc002.client.opencode import plugin_path


class WatchCommandTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {
            "XDG_CONFIG_HOME": tmp,
            "CODEX_HOME": str(Path(tmp) / "codex"),
        }))
        self.enterContext(patch("ulanzi_tc002.client.config.load_client_config", return_value={}))
        self.output = self.enterContext(patch("sys.stdout", new_callable=io.StringIO))
        self.request = self.enterContext(patch("ulanzi_tc002.client.cli.request", return_value={"accepted": True}))

    def run_commands(self, commands, *args):
        with patch("sys.stdin", io.StringIO(commands)):
            main(["watch", "agents", "--bridge-port", "0", *args])

    def test_add_remove_all_and_add_again(self):
        self.run_commands("a opencode\na codex\nr opencode\nr all\na opencode\n")
        created = [
            call.kwargs["json_body"]["name"] for call in self.request.call_args_list
            if call.args[0].endswith("/api/apps")
        ]
        deleted = [
            call.args[0].rsplit("/", 1)[-1] for call in self.request.call_args_list
            if call.kwargs["method"] == "DELETE"
        ]
        self.assertEqual(created, ["opencode", "codex", "opencode"])
        self.assertEqual(deleted, ["opencode", "codex", "opencode"])
        self.assertFalse(plugin_path().exists())
        self.assertIn("Active: (none)", self.output.getvalue())
        self.assertIn("Removed all providers", self.output.getvalue())
        self.assertIn("codex IDLE", self.output.getvalue())

    def test_invalid_and_duplicate_commands_do_not_stop_watching(self):
        self.run_commands("\na\nx codex\na unknown\na all\na opencode extra\na opencode\na opencode\nr codex\nr opencode\nr opencode\n")
        creates = [call for call in self.request.call_args_list if call.args[0].endswith("/api/apps")]
        deletes = [call for call in self.request.call_args_list if call.kwargs["method"] == "DELETE"]
        self.assertEqual(len(creates), 1)
        self.assertEqual(len(deletes), 1)
        self.assertIn("Error: Unknown provider: unknown", self.output.getvalue())
        self.assertIn("opencode is already active", self.output.getvalue())
        self.assertIn("codex is not active", self.output.getvalue())
        self.assertIn("opencode is not active", self.output.getvalue())

    def test_failed_setup_rolls_back_and_next_command_works(self):
        from ulanzi_tc002.client.opencode import install_plugin

        def fail_after_install(bridge_url):
            install_plugin(bridge_url)
            raise OSError("installation failed")

        with patch("ulanzi_tc002.client.watch.install_plugin", side_effect=fail_after_install):
            self.run_commands("a opencode\na codex\n")
        self.assertFalse(plugin_path().exists())
        self.assertIn("Error: installation failed", self.output.getvalue())
        self.assertIn("Added codex", self.output.getvalue())
        deletes = [call.args[0].rsplit("/", 1)[-1] for call in self.request.call_args_list if call.kwargs["method"] == "DELETE"]
        self.assertEqual(deletes, ["opencode", "codex"])

    def test_polls_while_stdin_is_idle(self):
        read_fd, write_fd = os.pipe()
        reader = self.enterContext(os.fdopen(read_fd))
        writer = self.enterContext(os.fdopen(write_fd, "w"))
        done = threading.Event()
        failures = []
        with patch("sys.stdin", reader):
            def watch():
                try:
                    main(["watch", "agents", "--providers", "opencode", "--bridge-port", "0", "--interval", "0.01"])
                except BaseException as error:
                    failures.append(error)
                finally:
                    done.set()

            polled = threading.Event()
            snapshots = 0
            original = BridgeStore.snapshot

            def snapshot(store, provider):
                nonlocal snapshots
                snapshots += 1
                if snapshots >= 3:
                    polled.set()
                return original(store, provider)

            with patch.object(BridgeStore, "snapshot", snapshot):
                thread = threading.Thread(target=watch, daemon=True)
                thread.start()
                try:
                    self.assertTrue(polled.wait(3), "watching stopped while stdin was idle")
                    writer.write("r all\na opencode\n")
                    writer.flush()
                finally:
                    writer.close()
                    self.assertTrue(done.wait(3), "watcher did not exit on EOF")
                    thread.join(timeout=1)
        self.assertEqual(failures, [])
        self.assertIn("Removed all providers", self.output.getvalue())
        self.assertIn("Added opencode", self.output.getvalue())
        self.assertFalse(plugin_path().exists())


class DynamicBridgeTests(unittest.TestCase):
    def test_removed_provider_rejects_updates_and_restarts_empty(self):
        store = BridgeStore()
        bridge = Bridge("127.0.0.1", 0, store, [])
        bridge.start()
        self.addCleanup(bridge.stop)
        request = Request(bridge.url + "/providers/codex", data=json.dumps({
            "hook_event_name": "UserPromptSubmit", "session_id": "s1",
        }).encode(), method="POST")
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=2)
        self.assertEqual(error.exception.code, 404)
        bridge.add_provider("codex")
        with urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 204)
        self.assertEqual(store.snapshot("codex")[:2], ("run", 1))
        bridge.remove_provider("codex")
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=2)
        self.assertEqual(error.exception.code, 404)
        bridge.add_provider("codex")
        self.assertEqual(store.snapshot("codex")[:2], ("idle", 0))


if __name__ == "__main__":
    unittest.main()
