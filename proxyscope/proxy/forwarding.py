from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from proxyscope.proxy.http1_request_rewriter import rewrite_cache_invalidation_headers
from proxyscope.proxy.runtime import CachePolicy

STREAM_CHUNK_SIZE = 64 * 1024
BODY_PREVIEW_BYTES = 4096


@dataclass(frozen=True)
class ForwardRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes = b""


@dataclass(frozen=True)
class ForwardResponse:
    status_code: int
    reason: str
    headers: dict[str, str]
    body: bytes
    body_size: int | None = None


class UpstreamForwarder:
    """Forward a request to its dynamic upstream target."""

    def __init__(self, *, cache_policy: CachePolicy) -> None:
        self._cache_policy = cache_policy

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
        headers = prepare_forward_headers(
            request.headers,
            cache_invalidation_enabled=self._cache_policy.cache_invalidation_enabled,
        )
        return requests.request(
            request.method,
            url,
            headers=headers,
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


def _apply_cache_invalidation_headers(headers: dict[str, str]) -> None:
    """
    Force upstream cache re-fetch by removing conditional validators and
    setting explicit no-cache request directives.
    """
    rewritten = rewrite_cache_invalidation_headers(headers)
    headers.clear()
    headers.update(rewritten)


def prepare_forward_headers(headers: dict[str, str], *, cache_invalidation_enabled: bool) -> dict[str, str]:
    prepared = dict(headers)
    if cache_invalidation_enabled:
        _apply_cache_invalidation_headers(prepared)
    return prepared


def prepare_forward_request(request: ForwardRequest) -> ForwardRequest:
    return request
