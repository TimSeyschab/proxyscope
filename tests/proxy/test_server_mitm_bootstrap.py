import unittest
from unittest.mock import Mock, patch

from proxyscope.mitm.certificates import MitmCertificateError
from proxyscope.proxy.server import ProxyHTTPServer, create_server


class TestServerMitmBootstrap(unittest.TestCase):
    def test_create_server_bootstraps_ca_when_auto_enable_is_on(self) -> None:
        fake_ca = Mock()
        fake_ca.ensure_ca_material.return_value = False

        with patch("proxyscope.proxy.server.default_ca", return_value=fake_ca):
            server = create_server("127.0.0.1", 0, auto_enable_mitm=True)
        try:
            self.assertIsInstance(server, ProxyHTTPServer)
            self.assertIsNotNone(server.mitm_interceptor)
            fake_ca.ensure_ca_material.assert_called_once_with()
        finally:
            server.server_close()

    def test_create_server_disables_mitm_when_ca_bootstrap_fails(self) -> None:
        fake_ca = Mock()
        fake_ca.ensure_ca_material.side_effect = MitmCertificateError("boom")

        with patch("proxyscope.proxy.server.default_ca", return_value=fake_ca):
            with self.assertLogs("tproxy.server", level="WARNING") as captured:
                server = create_server("127.0.0.1", 0, auto_enable_mitm=True)
        try:
            self.assertIsNone(server.mitm_interceptor)
            self.assertIn("MITM disabled: failed to initialize local CA: boom", "\n".join(captured.output))
            fake_ca.ensure_ca_material.assert_called_once_with()
        finally:
            server.server_close()

    def test_create_server_skips_ca_bootstrap_when_auto_enable_is_off(self) -> None:
        with patch("proxyscope.proxy.server.default_ca") as default_ca_mock:
            server = create_server("127.0.0.1", 0, auto_enable_mitm=False)
        try:
            self.assertIsNone(server.mitm_interceptor)
            default_ca_mock.assert_not_called()
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
