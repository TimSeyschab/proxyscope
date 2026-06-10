from typing import Protocol, runtime_checkable

from proxyscope.processing.models import ExchangeRequest, ExchangeResponse


class StaticResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def reason(self) -> str: ...

    @property
    def headers(self) -> dict[str, str]: ...

    @property
    def body(self) -> bytes: ...


@runtime_checkable
class PolicyEvaluator(Protocol):
    def should_modify_response_for_request(self, *, method: str, url: str) -> bool: ...

    def get_static_response_template_for_request(self, *, method: str, url: str) -> StaticResponse | None: ...


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


@runtime_checkable
class ResponseTransformer(Protocol):
    def maybe_modify_response(
        self,
        *,
        request_url: str,
        method: str,
        response: ExchangeResponse,
    ) -> ExchangeResponse: ...


@runtime_checkable
class RuntimeEventSink(Protocol):
    def on_site_visit(self, host: str) -> None: ...


@runtime_checkable
class CachePolicy(Protocol):
    @property
    def cache_invalidation_enabled(self) -> bool: ...


class RequestMiddleware(Protocol):
    def process_request(self, request: ExchangeRequest) -> ExchangeRequest: ...


class ResponseMiddleware(Protocol):
    def process_response(self, request: ExchangeRequest, response: ExchangeResponse) -> ExchangeResponse: ...
