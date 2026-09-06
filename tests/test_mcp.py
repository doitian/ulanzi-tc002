import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from ulanzi_tc002.server.config import Settings
from ulanzi_tc002.server.mcp import build_mcp
from ulanzi_tc002.server.registry import Registry


class McpTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_and_text_tools(self):
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
                    sent = await client.call_tool("text_send", {"text": "HI", "color": "blue"})
                    self.assertFalse(sent.is_error)
                    current = await client.call_tool("text_get", {})
                    self.assertFalse(current.is_error)
                    self.assertIn("HI", str(current.content) + str(current.structured_content))
            finally:
                registry.stop()
