import socket
from typing import Protocol

from proxyscope.adapters.proxy.connect import ConnectTarget
from proxyscope.application.processing.ports import Forwarder, ForwardRequest, ForwardResponse, StreamingForwarder


class TunnelInterceptor(Protocol):
    def intercept(self, *, client_socket: socket.socket, target: ConnectTarget, timeout_s: float = 30.0) -> bool: ...


__all__ = ["ForwardRequest", "ForwardResponse", "Forwarder", "StreamingForwarder", "TunnelInterceptor"]
