import unittest
import socket

from proxyscope.proxy.connect_tunnel import ConnectTarget, ConnectUpstreamConnectionError, handle_connect_tunnel, parse_connect_target


class TestConnectTunnelStubs(unittest.TestCase):
    def test_parse_connect_target_valid(self) -> None:
        target = parse_connect_target("example.com:443")
        self.assertEqual(target, ConnectTarget(host="example.com", port=443))

    def test_parse_connect_target_invalid_format(self) -> None:
        with self.assertRaises(ValueError):
            parse_connect_target("https://example.com:443")

    def test_parse_connect_target_invalid_port(self) -> None:
        with self.assertRaises(ValueError):
            parse_connect_target("example.com:70000")

    def test_connect_tunnel_raises_connection_error_for_unreachable_upstream(self) -> None:
        client, peer = socket.socketpair()
        try:
            with self.assertRaises(ConnectUpstreamConnectionError):
                handle_connect_tunnel(
                    client_socket=client,
                    target=ConnectTarget(host="127.0.0.1", port=1),
                    timeout_s=0.2,
                )
        finally:
            client.close()
            peer.close()
