from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ulanzi_tc002.client.config import load_client_config, resolve_endpoint, token_from_gopass


class ClientConfigTests(unittest.TestCase):
    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(load_client_config(Path(folder) / "missing.toml"), {})

    def test_reads_url_and_token(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            path.write_text('url = "http://10.0.0.5:9000"\ntoken = "secret"\n', encoding="utf-8")
            self.assertEqual(load_client_config(path), {"url": "http://10.0.0.5:9000", "token": "secret"})

    def test_reads_server_table(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            path.write_text('[server]\nurl = "https://clock.example:8443"\n', encoding="utf-8")
            self.assertEqual(load_client_config(path), {"url": "https://clock.example:8443"})

    def test_config_url_used_when_nothing_overrides(self):
        endpoint = resolve_endpoint(config={"url": "http://10.0.0.5:9000"}, environ={})
        self.assertEqual(endpoint["url"], "http://10.0.0.5:9000")
        self.assertEqual(endpoint["port"], 9000)

    def test_cli_url_overrides_config(self):
        endpoint = resolve_endpoint(
            url="http://override:8008", config={"url": "http://10.0.0.5:9000"}, environ={})
        self.assertEqual(endpoint["url"], "http://override:8008")

    def test_env_overrides_config(self):
        endpoint = resolve_endpoint(
            config={"url": "http://10.0.0.5:9000"},
            environ={"TC002_SERVER_URL": "http://from-env:8008"})
        self.assertEqual(endpoint["url"], "http://from-env:8008")

    def test_host_and_port_override_url(self):
        endpoint = resolve_endpoint(
            host="other", port=9001, config={"url": "http://10.0.0.5:9000"}, environ={})
        self.assertEqual(endpoint["url"], "http://other:9001")

    def test_token_from_config_unless_env_or_cli(self):
        config = {"url": "http://10.0.0.5:9000", "token": "from-config"}
        self.assertEqual(resolve_endpoint(config=config, environ={})["token"], "from-config")
        self.assertEqual(
            resolve_endpoint(config=config, environ={"TC002_TOKEN": "from-env"})["token"],
            "from-env")
        self.assertEqual(resolve_endpoint(token="cli", config=config, environ={})["token"], "cli")

    def test_default_url(self):
        self.assertEqual(resolve_endpoint(config={}, environ={})["url"], "http://127.0.0.1:8008")

    def test_invalid_url(self):
        with self.assertRaises(ValueError):
            resolve_endpoint(url="not-a-url", config={}, environ={})

    def test_reads_token_gopass(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            path.write_text('token_gopass = " infra/tc002 "\n', encoding="utf-8")
            self.assertEqual(load_client_config(path), {"token_gopass": "infra/tc002"})

    def test_token_gopass_must_be_nonempty_string(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            path.write_text("token_gopass = \"\"\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_client_config(path)

    def test_token_from_gopass(self):
        completed = subprocess.CompletedProcess(
            ["gopass", "show", "--password", "infra/tc002"], 0, stdout="secret\n", stderr="")
        with patch("ulanzi_tc002.client.config.subprocess.run", return_value=completed) as run:
            self.assertEqual(token_from_gopass("infra/tc002"), "secret")
        run.assert_called_once_with(
            ["gopass", "show", "--password", "infra/tc002"],
            check=True, capture_output=True, text=True)

    def test_token_from_gopass_missing_and_empty(self):
        with patch("ulanzi_tc002.client.config.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(ValueError):
                token_from_gopass("infra/tc002")
        completed = subprocess.CompletedProcess(
            ["gopass", "show", "--password", "infra/tc002"], 0, stdout="\n", stderr="")
        with patch("ulanzi_tc002.client.config.subprocess.run", return_value=completed):
            with self.assertRaises(ValueError):
                token_from_gopass("infra/tc002")

    def test_token_from_gopass_when_no_other_token(self):
        with patch("ulanzi_tc002.client.config.token_from_gopass", return_value="from-gopass") as gopass:
            endpoint = resolve_endpoint(config={"token_gopass": "infra/tc002"}, environ={})
        self.assertEqual(endpoint["token"], "from-gopass")
        gopass.assert_called_once_with("infra/tc002")

    def test_gopass_not_used_when_token_present(self):
        config = {"token": "from-config", "token_gopass": "infra/tc002"}
        with patch("ulanzi_tc002.client.config.token_from_gopass") as gopass:
            self.assertEqual(resolve_endpoint(config=config, environ={})["token"], "from-config")
            self.assertEqual(
                resolve_endpoint(config=config, environ={"TC002_TOKEN": "from-env"})["token"],
                "from-env")
            self.assertEqual(resolve_endpoint(token="cli", config=config, environ={})["token"], "cli")
        gopass.assert_not_called()
