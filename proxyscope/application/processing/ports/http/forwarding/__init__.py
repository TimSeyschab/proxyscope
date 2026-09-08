from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from proxyscope.application.processing.models import ExchangeResponse

STREAM_CHUNK_SIZE = 64 * 1024
BODY_PREVIEW_BYTES = 4096
ForwardResponse = ExchangeResponse


class UpstreamForwardingError(Exception):
    """The proxy could not establish or maintain an upstream HTTP connection."""


@dataclass(frozen=True)
class ForwardRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes = b""


class ForwardResponseStream(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def reason(self) -> str: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def iter_body_chunks(self, chunk_size: int) -> Iterable[bytes]: ...

    def close(self) -> None: ...


@runtime_checkable
class Forwarder(Protocol):
    def forward(self, request: ForwardRequest) -> ForwardResponse: ...


@runtime_checkable
class StreamingForwarder(Forwarder, Protocol):
    def open_stream(self, request: ForwardRequest) -> ForwardResponseStream: ...


def capture_body_preview(
    chunks: Iterable[bytes],
    *,
    max_bytes: int = BODY_PREVIEW_BYTES,
    on_chunk: Callable[[bytes], None] | None = None,
) -> tuple[bytes, int]:
    preview = bytearray()
    total_bytes = 0
    for chunk in chunks:
        if not chunk:
            continue
        if on_chunk is not None:
            on_chunk(chunk)
        total_bytes += len(chunk)
        remaining = max_bytes - len(preview)
        if remaining > 0:
            preview.extend(chunk[:remaining])
    return bytes(preview), total_bytes
