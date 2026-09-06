from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from ulanzi_tc002.frames import image_data_uri
from ulanzi_tc002.server.config import Settings
from ulanzi_tc002.server.main import create_app

from test_image import png_bytes


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

    def _add(self, name, kind="text"):
        created = self.client.post("/api/apps", json={"name": name, "type": kind})
        self.assertEqual(created.status_code, 200)
        return created.json()

    def test_health_and_text_roundtrip(self):
        self.assertEqual(self.client.get("/api/health").json(), {"ok": True})
        self._add("hello")
        posted = self.client.post("/api/apps/hello", json={"text": "HI", "color": "blue"})
        self.assertEqual(posted.status_code, 200)
        self.assertEqual(posted.json()["accepted"], True)
        self.assertEqual(posted.json()["color"], "#82AAE8")
        current = self.client.get("/api/apps/hello").json()
        self.assertEqual(current["text"], "HI")
        self.assertEqual(current["type"], "text")

    def test_delete_removes_app(self):
        self._add("hello")
        self.client.post("/api/apps/hello", json={"text": "HI"})
        deleted = self.client.delete("/api/apps/hello")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])
        self.assertEqual(self.client.get("/api/apps/hello").status_code, 404)
        rejected = self.client.post("/api/apps/hello", json={"text": "NO"})
        self.assertEqual(rejected.status_code, 404)

    def test_unknown_app(self):
        self.assertEqual(self.client.get("/api/apps/missing").status_code, 404)

    def test_invalid_text_is_400(self):
        self._add("hello")
        response = self.client.post("/api/apps/hello", json={"text": "not ascii \u2603"})
        self.assertEqual(response.status_code, 400)

    def test_apps_list_starts_empty_and_create_duplicate(self):
        self.assertEqual(self.client.get("/api/apps").json(), [])
        self._add("hello")
        names = [app["name"] for app in self.client.get("/api/apps").json()]
        self.assertEqual(names, ["hello"])
        duplicate = self.client.post("/api/apps", json={"name": "hello", "type": "text"})
        self.assertEqual(duplicate.status_code, 409)

    def test_multiple_apps_same_type(self):
        self._add("one")
        self._add("two")
        self._add("cat", "image")
        self.client.post("/api/apps/one", json={"text": "A"})
        self.client.post("/api/apps/two", json={"text": "B"})
        listed = {app["name"]: app for app in self.client.get("/api/apps").json()}
        self.assertEqual(listed["one"]["text"], "A")
        self.assertEqual(listed["two"]["text"], "B")
        self.assertEqual(listed["cat"]["type"], "image")

    def test_image_roundtrip(self):
        self._add("cat", "image")
        posted = self.client.post("/api/apps/cat", json={"image": image_data_uri(png_bytes())})
        self.assertEqual(posted.status_code, 200)
        self.assertTrue(posted.json()["accepted"])
        current = self.client.get("/api/apps/cat").json()
        self.assertTrue(current["image"].startswith("data:image/png;base64,"))
        frame = self.device.post.call_args.args[2]
        self.assertEqual(frame["image"][0]["position"], [0, 0])

    def test_apps_persist_across_restart(self):
        self._add("hello")
        self.client.post("/api/apps/hello", json={"text": "HI", "color": "blue"})
        self._add("cat", "image")
        self.client.post("/api/apps/cat", json={"image": image_data_uri(png_bytes())})
        self.cm.__exit__(None, None, None)
        self.cm = self._client(Settings(data_dir=Path(self.tmp.name)))
        self.client = self.cm.__enter__()
        apps = {app["name"]: app for app in self.client.get("/api/apps").json()}
        self.assertEqual(apps["hello"]["text"], "HI")
        self.assertEqual(apps["hello"]["type"], "text")
        self.assertEqual(apps["cat"]["type"], "image")
        self.assertTrue(apps["cat"]["image"].startswith("data:image/png;base64,"))

    def test_list_includes_device_apps_and_delete(self):
        self.device.custom_list.return_value = {"apps": ["text", "hello"]}
        self._add("hello")
        listed = self.client.get("/api/apps").json()
        names = [app["name"] for app in listed]
        self.assertEqual(names, ["hello", "text"])
        leftover = next(app for app in listed if app["name"] == "text")
        self.assertIsNone(leftover["type"])
        self.assertTrue(leftover["on_device"])
        deleted = self.client.delete("/api/apps/text")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])

    def test_migrates_legacy_enabled_text_app(self):
        (Path(self.tmp.name) / "config.json").write_text(
            '{"apps": {"text": {"enabled": true}}}\n', encoding="utf-8")
        self.cm.__exit__(None, None, None)
        self.cm = self._client(Settings(data_dir=Path(self.tmp.name)))
        self.client = self.cm.__enter__()
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
        created = self.client.post(
            "/api/apps", json={"name": "hello", "type": "text"}, headers=headers)
        self.assertEqual(created.status_code, 200)
        posted = self.client.post(
            "/api/apps/hello", json={"text": "HI"}, headers=headers)
        self.assertEqual(posted.status_code, 200)
