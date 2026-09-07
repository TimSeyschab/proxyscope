from typing import Protocol, runtime_checkable

from proxyscope.application.processing.models import ExchangeResponse


@runtime_checkable
class ResponseTransformer(Protocol):
    def maybe_modify_response(
        self,
        *,
        request_url: str,
        method: str,
        response: ExchangeResponse,
        source_request_id: int | None = None,
    ) -> ExchangeResponse: ...
