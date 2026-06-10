import time
from collections.abc import Iterable

from proxyscope.processing.middleware import CacheInvalidationMiddleware
from proxyscope.processing.models import ExchangeRequest, ExchangeResponse, PreparedExchange
from proxyscope.processing.ports import (
    ExchangeRecorder,
    PolicyEvaluator,
    RequestMiddleware,
    ResponseMiddleware,
    ResponseTransformer,
    RuntimeEventSink,
)


class ExchangePipeline:
    def __init__(
        self,
        *,
        policy_evaluator: PolicyEvaluator,
        exchange_recorder: ExchangeRecorder,
        response_transformer: ResponseTransformer,
        runtime_events: RuntimeEventSink,
        cache_middleware: CacheInvalidationMiddleware,
        request_middlewares: Iterable[RequestMiddleware] = (),
        response_middlewares: Iterable[ResponseMiddleware] = (),
    ) -> None:
        self._policy_evaluator = policy_evaluator
        self._exchange_recorder = exchange_recorder
        self._response_transformer = response_transformer
        self._runtime_events = runtime_events
        self._cache_middleware = cache_middleware
        self._request_middlewares = (cache_middleware, *request_middlewares)
        self._response_middlewares = tuple(response_middlewares)

    def prepare_request(self, request: ExchangeRequest) -> PreparedExchange:
        started_at = time.perf_counter()
        processed = request
        for middleware in self._request_middlewares:
            processed = middleware.process_request(processed)

        request_id = self._exchange_recorder.record_request(
            method=processed.method,
            path=processed.path,
            client_ip=processed.client_ip,
            headers=processed.headers,
            body=processed.body,
            target_host=processed.target_host,
            target_port=processed.target_port,
            protocol=processed.protocol,
        )
        if processed.target_host:
            self._runtime_events.on_site_visit(processed.target_host)

        static_template = self._policy_evaluator.get_static_response_template_for_request(
            method=processed.method,
            url=processed.url,
        )
        static_response = None
        if static_template is not None:
            static_response = ExchangeResponse(
                status_code=static_template.status_code,
                reason=static_template.reason,
                headers=dict(static_template.headers),
                body=static_template.body,
                body_size=len(static_template.body),
            )
        transform_response = self._policy_evaluator.should_modify_response_for_request(
            method=processed.method,
            url=processed.url,
        )
        return PreparedExchange(
            request=processed,
            request_id=request_id,
            started_at=started_at,
            static_response=static_response,
            transform_response=transform_response,
            requires_buffered_response=static_response is not None
            or transform_response
            or bool(self._response_middlewares),
        )

    def process_response(
        self,
        exchange: PreparedExchange,
        response: ExchangeResponse,
        *,
        duration_ms: float | None = None,
    ) -> ExchangeResponse:
        final_response = exchange.static_response or response
        if exchange.static_response is None and exchange.transform_response:
            final_response = self._response_transformer.maybe_modify_response(
                request_url=exchange.request.url,
                method=exchange.request.method,
                response=final_response,
            )
        for middleware in self._response_middlewares:
            final_response = middleware.process_response(exchange.request, final_response)

        elapsed_ms = duration_ms
        if elapsed_ms is None:
            elapsed_ms = (time.perf_counter() - exchange.started_at) * 1000
        self._exchange_recorder.record_response(
            final_response,
            request_id=exchange.request_id,
            duration_ms=elapsed_ms,
            client_ip=exchange.request.client_ip,
            target_host=exchange.request.target_host,
        )
        return final_response

    def rewrite_request_headers(self, headers: dict[str, str]) -> dict[str, str]:
        return self._cache_middleware.rewrite_headers(headers)
