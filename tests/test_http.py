import unittest
from unittest.mock import patch

from ulanzi_tc002.http import is_lan_host, proxy_handler_for


class HttpTests(unittest.TestCase):
    def test_lan_ips_skip_proxy(self):
        for host in ("10.31.3.197", "192.168.1.1", "172.16.0.1", "127.0.0.1", "localhost"):
            handler = proxy_handler_for(host, "http://proxy:8080")
            self.assertEqual(handler.proxies, {}, host)

    def test_wan_ip_uses_proxy(self):
        with patch("ulanzi_tc002.http.proxy_bypass", return_value=False):
            handler = proxy_handler_for("8.8.8.8", "http://proxy:8080")
        self.assertEqual(handler.proxies.get("http"), "http://proxy:8080")

    def test_no_proxy_env_bypass(self):
        with patch("ulanzi_tc002.http.proxy_bypass", return_value=True):
            handler = proxy_handler_for("8.8.8.8", "http://proxy:8080")
        self.assertEqual(handler.proxies, {})

    def test_missing_proxy_disables_proxy(self):
        with patch("ulanzi_tc002.http.configured_proxy", return_value=None):
            handler = proxy_handler_for("8.8.8.8", None)
        self.assertEqual(handler.proxies, {})

    def test_is_lan_host(self):
        self.assertTrue(is_lan_host("10.0.0.1"))
        self.assertTrue(is_lan_host("localhost"))
        self.assertFalse(is_lan_host("8.8.8.8"))
        self.assertFalse(is_lan_host(""))
