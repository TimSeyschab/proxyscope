import unittest

from proxyscope.proxy.tunnel_registry import TunnelConnectionRegistry


class _ClosableSocket:
    def __init__(self, *, raises: bool = False) -> None:
        self.raises = raises
        self.closed = False

    def close(self) -> None:
        if self.raises:
            raise OSError("close failed")
        self.closed = True


class TestTunnelConnectionRegistry(unittest.TestCase):
    def test_close_all_closes_registered_sockets(self) -> None:
        registry = TunnelConnectionRegistry()
        first = _ClosableSocket()
        second = _ClosableSocket()
        registry.register(first)
        registry.register(second)

        closed = registry.close_all()

        self.assertEqual(closed, 2)
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)
        self.assertEqual(registry.close_all(), 0)

    def test_close_all_ignores_socket_close_errors(self) -> None:
        registry = TunnelConnectionRegistry()
        broken = _ClosableSocket(raises=True)
        ok = _ClosableSocket()
        registry.register(broken)
        registry.register(ok)

        closed = registry.close_all()

        self.assertEqual(closed, 1)
        self.assertTrue(ok.closed)

    def test_unregister_is_idempotent(self) -> None:
        registry = TunnelConnectionRegistry()
        sock = _ClosableSocket()
        registry.register(sock)
        registry.unregister(sock)
        registry.unregister(sock)

        self.assertEqual(registry.close_all(), 0)
