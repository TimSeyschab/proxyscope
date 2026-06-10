from typing import Protocol

from proxyscope.proxy.forwarding import ForwardRequest, ForwardResponse


class Forwarder(Protocol):
    def forward(self, request: ForwardRequest) -> ForwardResponse: ...
