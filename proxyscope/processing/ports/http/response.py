from typing import Protocol, runtime_checkable

from proxyscope.processing.models import ExchangeResponse


@runtime_checkable
class ResponseTransformer(Protocol):
    def maybe_modify_response(
        self,
        *,
        request_url: str,
        method: str,
        response: ExchangeResponse,
    ) -> ExchangeResponse: ...
