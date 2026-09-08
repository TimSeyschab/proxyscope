from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit

import requests

from proxyscope.application.processing.ports import (
    STREAM_CHUNK_SIZE,
    ForwardRequest,
    ForwardResponse,
    UpstreamForwardingError,
)


class RequestsForwardResponseStream:
    def __init__(self, response: requests.Response) -> None:
        self._response = response

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def reason(self) -> str:
        return self._response.reason

    @property
    def headers(self) -> Mapping[str, str]:
        return self._response.headers

    def iter_body_chunks(self, chunk_size: int) -> Iterable[bytes]:
        return self._response.raw.stream(chunk_size, decode_content=False)

    def close(self) -> None:
        self._response.close()


class UpstreamForwarder:
    """Forward a request to its dynamic upstream target."""

    def forward(self, request: ForwardRequest) -> ForwardResponse:
        stream = self.open_stream(request)
        try:
            body = b"".join(stream.iter_body_chunks(STREAM_CHUNK_SIZE))
            return ForwardResponse(
                stream.status_code,
                stream.reason,
                dict(stream.headers),
                body,
                body_size=len(body),
            )
        finally:
            stream.close()

    def open_stream(self, request: ForwardRequest) -> RequestsForwardResponseStream:
        url = resolve_target_url(request)
        try:
            response = requests.request(
                request.method,
                url,
                headers=request.headers,
                data=request.body,
                timeout=60,
                stream=True,
            )
        except requests.RequestException as exc:
            raise UpstreamForwardingError(f"Could not reach upstream {url}.") from exc
        return RequestsForwardResponseStream(response)


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
