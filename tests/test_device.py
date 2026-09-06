import ipaddress
import unittest
from unittest.mock import patch

from ulanzi_tc002.device import discovery_networks, local_networks


class DeviceDiscoveryTests(unittest.TestCase):
    def test_configured_network_is_used(self):
        networks = discovery_networks({"network": "192.0.2.0/24"})
        self.assertEqual(networks, [ipaddress.ip_network("192.0.2.0/24")])

    def test_oversized_network_rejected(self):
        with self.assertRaises(ValueError):
            discovery_networks({"network": "10.0.0.0/8"})

    @patch("ulanzi_tc002.device.local_ipv4s", return_value={"10.1.2.3", "127.0.0.1", "169.254.1.1"})
    def test_local_scan_uses_interface_slash24(self, _local_ipv4s):
        self.assertEqual(local_networks(), [ipaddress.ip_network("10.1.2.0/24")])
        networks = discovery_networks({"mac": "ccc4b277a363"})
        self.assertEqual(networks, [ipaddress.ip_network("10.1.2.0/24")])

    @patch("ulanzi_tc002.device.local_networks", return_value=[])
    def test_no_lan_explains_how_to_set_network(self, _local):
        with self.assertRaises(ConnectionError) as error:
            discovery_networks({"mac": "ccc4b277a363"})
        self.assertIn("TC002_DEVICE_IP", str(error.exception))
