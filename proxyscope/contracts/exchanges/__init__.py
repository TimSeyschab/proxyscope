from dataclasses import dataclass


@dataclass(frozen=True)
class ExchangeRequest:
    method: str
    url: str
    path: str
    headers: dict[str, str]
    body: bytes = b""
    client_ip: str = "unknown"
    target_host: str | None = None
    target_port: int | None = None
    protocol: str = "http"


@dataclass(frozen=True)
class ExchangeResponse:
    status_code: int
    reason: str
    headers: dict[str, str]
    body: bytes
    body_size: int | None = None


@dataclass(frozen=True)
class PreparedExchange:
    request: ExchangeRequest
    request_id: int | None
    started_at: float
    static_response: ExchangeResponse | None
    transform_response: bool
    requires_buffered_response: bool
