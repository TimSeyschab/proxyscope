from typing import Protocol, runtime_checkable

from proxyscope.application.processing.models import ExchangeResponse


@runtime_checkable
class ExchangeRecorder(Protocol):
    def record_request(
        self,
        *,
        method: str,
        path: str,
        client_ip: str,
        headers: dict[str, str],
        body: bytes = b"",
        target_host: str | None = None,
        target_port: int | None = None,
        protocol: str = "http",
    ) -> int | None: ...

    def record_response(
        self,
        response: ExchangeResponse,
        *,
        request_id: int | None,
        duration_ms: float,
        client_ip: str,
        target_host: str | None = None,
    ) -> None: ...
