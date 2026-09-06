import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from ulanzi_tc002.frames import image_data_uri
from ulanzi_tc002.server.config import Settings
from ulanzi_tc002.server.mcp import build_mcp
from ulanzi_tc002.server.registry import Registry

GIF = b"GIF89a" + b"\x00" * 8


class McpTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_create_text_and_image_tools(self):
        from mcp import Client
        with tempfile.TemporaryDirectory() as folder:
            device = Mock()
            device.post.return_value = {"code": 200}
            registry = Registry(Settings(data_dir=Path(folder)), device)
            registry.start()
            try:
                async with Client(build_mcp(registry)) as client:
                    listed = await client.call_tool("list_apps", {})
                    self.assertFalse(listed.is_error)
                    created = await client.call_tool("create_app", {"name": "hello", "type": "text"})
                    self.assertFalse(created.is_error)
                    sent = await client.call_tool(
                        "text_send", {"name": "hello", "text": "HI", "color": "blue"})
                    self.assertFalse(sent.is_error)
                    current = await client.call_tool("text_get", {"name": "hello"})
                    self.assertFalse(current.is_error)
                    self.assertIn("HI", str(current.content) + str(current.structured_content))
                    image = await client.call_tool("create_app", {"name": "cat", "type": "image"})
                    self.assertFalse(image.is_error)
                    posted = await client.call_tool(
                        "image_send", {"name": "cat", "image": image_data_uri(GIF)})
                    self.assertFalse(posted.is_error)
                    deleted = await client.call_tool("delete_app", {"name": "hello"})
                    self.assertFalse(deleted.is_error)
            finally:
                registry.stop()
