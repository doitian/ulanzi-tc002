from pathlib import Path
import tempfile
import unittest

from ulanzi_tc002.client.config import load_client_config, resolve_endpoint


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
