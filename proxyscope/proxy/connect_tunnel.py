import re
import selectors
import socket
from dataclasses import dataclass
from typing import cast

_AUTHORITY_PATTERN = re.compile(r"^(?P<host>[A-Za-z0-9.\-]+):(?P<port>\d{1,5})$")


@dataclass(frozen=True)
class ConnectTarget:
    host: str
    port: int


class ConnectTunnelError(Exception):
    """Base error type for CONNECT tunnel setup/relay failures."""


class ConnectUpstreamConnectionError(ConnectTunnelError):
    """Raised when upstream TCP connection cannot be established."""


class ConnectUpstreamTimeoutError(ConnectTunnelError):
    """Raised when upstream connection or relay times out."""


def parse_connect_target(authority: str) -> ConnectTarget:
    """
    Parse CONNECT authority-form target: "<host>:<port>".
    """
    match = _AUTHORITY_PATTERN.fullmatch(authority)
    if not match:
        raise ValueError("Invalid CONNECT target. Expected '<host>:<port>'.")

    host = match.group("host")
    port = int(match.group("port"))
    if port < 1 or port > 65535:
        raise ValueError("Invalid CONNECT port. Must be between 1 and 65535.")

    return ConnectTarget(host=host, port=port)


def handle_connect_tunnel(
    *,
    client_socket: socket.socket,
    target: ConnectTarget,
    timeout_s: float = 30.0,
) -> None:
    """
    Handle HTTPS CONNECT tunneling.

    Socket roles:
    - client_socket: existing TCP connection (client <-> proxy)
    - upstream_socket: new TCP connection (proxy <-> target)

    Flow:
    1) Open upstream socket to requested target.
    2) Send 200 Connection Established back to client.
    3) Relay bytes bidirectionally until one side closes.
    """
    try:
        # Step 1: open a separate proxy->upstream TCP connection.
        upstream_socket = socket.create_connection((target.host, target.port), timeout=timeout_s)
    except socket.timeout as exc:
        raise ConnectUpstreamTimeoutError(
            f"Timed out connecting to upstream target {target.host}:{target.port}."
        ) from exc
    except OSError as exc:
        raise ConnectUpstreamConnectionError(
            f"Failed to connect to upstream target {target.host}:{target.port}: {exc}"
        ) from exc

    # Upstream connection succeeded; now upgrade the client connection into a tunnel.
    with upstream_socket:
        client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        _relay_bidirectional(client_socket, upstream_socket, timeout_s=timeout_s)


def _relay_bidirectional(
    client_socket: socket.socket,
    upstream_socket: socket.socket,
    *,
    timeout_s: float,
) -> None:
    """
    Relay raw bytes client<->upstream until EOF or inactivity timeout.
    """
    client_socket.setblocking(False)
    upstream_socket.setblocking(False)

    selector = selectors.DefaultSelector()
    try:
        # For each readable socket, forward bytes to its opposite side.
        selector.register(client_socket, selectors.EVENT_READ, upstream_socket)
        selector.register(upstream_socket, selectors.EVENT_READ, client_socket)

        while True:
            events = selector.select(timeout=timeout_s)
            if not events:
                # Idle tunnel timeout: close gracefully instead of raising an HTTP-layer error.
                return

            for key, _mask in events:
                source_sock = cast(socket.socket, key.fileobj)
                destination_sock = cast(socket.socket, key.data)

                chunk = source_sock.recv(65536)

                # EOF on one side ends tunnel.
                if not chunk:
                    return

                destination_sock.sendall(chunk)
    finally:
        selector.close()
