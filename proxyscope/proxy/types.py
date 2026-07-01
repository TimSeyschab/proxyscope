import socket
from typing import Protocol

from proxyscope.processing.ports import Forwarder, ForwardRequest, ForwardResponse, StreamingForwarder
from proxyscope.proxy.connect import ConnectTarget


class TunnelInterceptor(Protocol):
    def intercept(self, *, client_socket: socket.socket, target: ConnectTarget, timeout_s: float = 30.0) -> bool: ...


__all__ = ["ForwardRequest", "ForwardResponse", "Forwarder", "StreamingForwarder", "TunnelInterceptor"]
