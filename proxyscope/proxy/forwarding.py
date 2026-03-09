from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from proxyscope.app.config.runtime import is_cache_invalidation_enabled
from proxyscope.proxy.http1_request_rewriter import rewrite_cache_invalidation_headers


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


class UpstreamForwarder:
    """Forward a request to its dynamic upstream target."""

    def forward(self, request: ForwardRequest) -> ForwardResponse:
        url = resolve_target_url(request)
        headers = prepare_forward_headers(request.headers)
        response = requests.request(request.method,
                                    url,
                                    headers=headers,
                                    data=request.body,
                                    timeout=60)
        return ForwardResponse(response.status_code,
                               response.reason,
                               dict(response.headers),
                               response.content)


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


def prepare_forward_headers(headers: dict[str, str]) -> dict[str, str]:
    prepared = dict(headers)
    if is_cache_invalidation_enabled():
        _apply_cache_invalidation_headers(prepared)
    return prepared


def prepare_forward_request(request: ForwardRequest) -> ForwardRequest:
    return request
