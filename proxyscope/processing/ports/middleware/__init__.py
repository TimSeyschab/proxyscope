from typing import Protocol

from proxyscope.processing.models import ExchangeRequest, ExchangeResponse


class RequestMiddleware(Protocol):
    def process_request(self, request: ExchangeRequest) -> ExchangeRequest: ...


class ResponseMiddleware(Protocol):
    def process_response(self, request: ExchangeRequest, response: ExchangeResponse) -> ExchangeResponse: ...
