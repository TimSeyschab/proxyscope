from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from proxyscope.processing.models import ExchangeResponse as ForwardResponse

STREAM_CHUNK_SIZE = 64 * 1024
BODY_PREVIEW_BYTES = 4096


@dataclass(frozen=True)
class ForwardRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes = b""


class UpstreamForwarder:
    """Forward a request to its dynamic upstream target."""

    def forward(self, request: ForwardRequest) -> ForwardResponse:
        response = self.open_stream(request)
        try:
            body = response.content
            return ForwardResponse(
                response.status_code,
                response.reason,
                dict(response.headers),
                body,
                body_size=len(body),
            )
        finally:
            response.close()

    def open_stream(self, request: ForwardRequest) -> requests.Response:
        url = resolve_target_url(request)
        return requests.request(
            request.method,
            url,
            headers=request.headers,
            data=request.body,
            timeout=60,
            stream=True,
        )


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


def resolve_target_url(request: ForwardRequest) -> str:
    if request.path.startswith(("http://", "https://")):
        parsed = urlsplit(request.path)
        if not parsed.netloc:
            raise ValueError("Invalid absolute-form request target.")
        return request.path

    host = request.headers.get("Host")
    if not host:
        raise ValueError("Missing Host header for dynamic forward proxy request.")

    normalized_path = request.path if request.path.startswith("/") else f"/{request.path}"
    return f"http://{host}{normalized_path}"


def prepare_forward_request(request: ForwardRequest) -> ForwardRequest:
    return request
