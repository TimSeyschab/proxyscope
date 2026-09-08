from typing import Protocol, runtime_checkable

from proxyscope.contracts.exchanges import ExchangeRequest, ExchangeResponse


@runtime_checkable
class TrafficRuleEvaluator(Protocol):
    def prepare_request(self, request: ExchangeRequest) -> tuple[ExchangeRequest, ExchangeResponse | None]: ...

    def process_response(
        self, request: ExchangeRequest, response: ExchangeResponse, *, request_id: int | None
    ) -> ExchangeResponse: ...

    def requires_buffered_response(self, request: ExchangeRequest) -> bool: ...

    def should_open_editor(self, request: ExchangeRequest, response: ExchangeResponse) -> bool: ...
