from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from ulanzi_tc002.server.config import Settings
from ulanzi_tc002.server.main import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.device = Mock()
        self.device.address = "10.31.3.197"
        self.device.post.return_value = {"code": 200}
        settings = Settings(data_dir=Path(self.tmp.name))
        self.cm = self._client(settings)
        self.client = self.cm.__enter__()

    def _client(self, settings):
        from fastapi.testclient import TestClient
        return TestClient(create_app(settings, self.device))

    def tearDown(self):
        self.cm.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_health_and_text_roundtrip(self):
        self.assertEqual(self.client.get("/api/health").json(), {"ok": True})
        posted = self.client.post("/api/apps/text", json={"text": "HI", "color": "blue"})
        self.assertEqual(posted.status_code, 200)
        self.assertEqual(posted.json()["accepted"], True)
        self.assertEqual(posted.json()["color"], "#82AAE8")
        current = self.client.get("/api/apps/text").json()
        self.assertEqual(current["text"], "HI")
        alias = self.client.post("/text", json={"text": "OK"})
        self.assertEqual(alias.status_code, 200)
        self.assertEqual(self.client.get("/text").json()["text"], "OK")

    def test_disable_rejects_writes_and_enable_restores(self):
        self.client.post("/api/apps/text", json={"text": "HI"})
        disabled = self.client.post("/api/apps/text/disable")
        self.assertFalse(disabled.json()["enabled"])
        rejected = self.client.post("/api/apps/text", json={"text": "NO"})
        self.assertEqual(rejected.status_code, 409)
        enabled = self.client.post("/api/apps/text/enable")
        self.assertTrue(enabled.json()["enabled"])
        posted = self.client.post("/api/apps/text", json={"text": "YES"})
        self.assertEqual(posted.status_code, 200)
        self.assertEqual(posted.json()["text"], "YES")

    def test_unknown_app(self):
        self.assertEqual(self.client.get("/api/apps/missing").status_code, 404)

    def test_invalid_text_is_400(self):
        response = self.client.post("/api/apps/text", json={"text": "not ascii \u2603"})
        self.assertEqual(response.status_code, 400)

    def test_apps_list_includes_text(self):
        names = [app["name"] for app in self.client.get("/api/apps").json()]
        self.assertEqual(names, ["text"])


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.device = Mock()
        self.device.address = "10.31.3.197"
        self.device.post.return_value = {"code": 200}
        settings = Settings(data_dir=Path(self.tmp.name), token="secret")
        from fastapi.testclient import TestClient
        self.cm = TestClient(create_app(settings, self.device))
        self.client = self.cm.__enter__()

    def tearDown(self):
        self.cm.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_token_required_except_health_and_ui(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/apps").status_code, 401)
        headers = {"Authorization": "Bearer secret"}
        self.assertEqual(self.client.get("/api/apps", headers=headers).status_code, 200)
        posted = self.client.post("/api/apps/text", json={"text": "HI"}, headers=headers)
        self.assertEqual(posted.status_code, 200)
