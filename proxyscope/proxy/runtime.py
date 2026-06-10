from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from proxyscope.proxy.forwarding import ForwardResponse


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
        response: ForwardResponse,
        *,
        request_id: int | None,
        duration_ms: float,
        client_ip: str,
        target_host: str | None = None,
    ) -> None: ...

    def record_mitm_request(
        self,
        *,
        client_ip: str,
        target_host: str,
        target_port: int,
        start_line: str,
        headers: dict[str, str],
        body: bytes,
    ) -> int | None: ...

    def record_mitm_response(
        self,
        *,
        client_ip: str,
        target_host: str,
        target_port: int,
        start_line: str,
        headers: dict[str, str],
        body: bytes,
        request_id: int | None,
    ) -> None: ...


@runtime_checkable
class ResponseTransformer(Protocol):
    def maybe_modify_response(self, *, request_url: str, method: str, response: ForwardResponse) -> ForwardResponse: ...


@runtime_checkable
class RuntimeEventSink(Protocol):
    def on_site_visit(self, host: str) -> None: ...


@runtime_checkable
class CachePolicy(Protocol):
    @property
    def cache_invalidation_enabled(self) -> bool: ...


@dataclass(frozen=True)
class ProxyRuntimeContext:
    policy_evaluator: PolicyEvaluator
    exchange_recorder: ExchangeRecorder
    response_transformer: ResponseTransformer
    runtime_events: RuntimeEventSink
    cache_policy: CachePolicy
