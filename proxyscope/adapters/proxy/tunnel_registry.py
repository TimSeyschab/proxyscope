from threading import Lock


class TunnelConnectionRegistry:
    """
    Thread-safe registry for currently active CONNECT/TLS tunnel sockets.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._sockets: set[object] = set()

    def register(self, sock: object) -> None:
        with self._lock:
            self._sockets.add(sock)

    def unregister(self, sock: object) -> None:
        with self._lock:
            self._sockets.discard(sock)

    def close_all(self) -> int:
        with self._lock:
            sockets = list(self._sockets)
            self._sockets.clear()

        closed = 0
        for sock in sockets:
            try:
                sock.close()  # type: ignore[attr-defined]
                closed += 1
            except OSError:
                pass
        return closed
