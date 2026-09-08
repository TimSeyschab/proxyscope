import time
from collections.abc import Callable, Iterable

from proxyscope.application.processing.middleware import CacheInvalidationMiddleware
from proxyscope.application.processing.models import ExchangeRequest, ExchangeResponse, PreparedExchange
from proxyscope.application.processing.ports import (
    ExchangeRecorder,
    RequestMiddleware,
    ResponseMiddleware,
    ResponseTransformer,
    RuntimeEventSink,
    TrafficRuleEvaluator,
)


class ExchangePipeline:
    def __init__(
        self,
        *,
        exchange_recorder: ExchangeRecorder,
        response_transformer: ResponseTransformer,
        runtime_events: RuntimeEventSink,
        cache_middleware: CacheInvalidationMiddleware,
        request_middlewares: Iterable[RequestMiddleware] = (),
        response_middlewares: Iterable[ResponseMiddleware] = (),
        dynamic_request_middlewares: Callable[[], tuple[RequestMiddleware, ...]] | None = None,
        dynamic_response_middlewares: Callable[[], tuple[ResponseMiddleware, ...]] | None = None,
        mock_response_for: Callable[[str, str], ExchangeResponse | None] | None = None,
        traffic_rule_evaluator: TrafficRuleEvaluator | None = None,
    ) -> None:
        self._exchange_recorder = exchange_recorder
        self._response_transformer = response_transformer
        self._runtime_events = runtime_events
        self._cache_middleware = cache_middleware
        self._request_middlewares = (cache_middleware, *request_middlewares)
        self._response_middlewares = tuple(response_middlewares)
        self._dynamic_request_middlewares = dynamic_request_middlewares
        self._dynamic_response_middlewares = dynamic_response_middlewares
        self._mock_response_for = mock_response_for
        self._traffic_rule_evaluator = traffic_rule_evaluator

    def prepare_request(self, request: ExchangeRequest) -> PreparedExchange:
        started_at = time.perf_counter()
        processed = request
        dynamic_request = () if self._dynamic_request_middlewares is None else self._dynamic_request_middlewares()
        for middleware in (*self._request_middlewares, *dynamic_request):
            processed = middleware.process_request(processed)

        rule_response = None
        if self._traffic_rule_evaluator is not None:
            processed, rule_response = self._traffic_rule_evaluator.prepare_request(processed)

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
        mock_response = (
            None if self._mock_response_for is None else self._mock_response_for(processed.method, processed.url)
        )
        static_response = None
        if rule_response is not None:
            static_response = rule_response
        elif mock_response is not None:
            static_response = mock_response
        transform_response = (
            self._traffic_rule_evaluator is not None
            and self._traffic_rule_evaluator.requires_buffered_response(processed)
        )
        return PreparedExchange(
            request=processed,
            request_id=request_id,
            started_at=started_at,
            static_response=static_response,
            transform_response=transform_response,
            requires_buffered_response=static_response is not None
            or transform_response
            or bool(self._response_middlewares)
            or bool(() if self._dynamic_response_middlewares is None else self._dynamic_response_middlewares()),
        )

    def process_response(
        self,
        exchange: PreparedExchange,
        response: ExchangeResponse,
        *,
        duration_ms: float | None = None,
    ) -> ExchangeResponse:
        final_response = exchange.static_response or response
        if (
            exchange.static_response is None
            and exchange.transform_response
            and self._traffic_rule_evaluator is not None
            and self._traffic_rule_evaluator.should_open_editor(exchange.request, final_response)
        ):
            final_response = self._response_transformer.maybe_modify_response(
                request_url=exchange.request.url,
                method=exchange.request.method,
                response=final_response,
                source_request_id=exchange.request_id,
            )
        dynamic_response = () if self._dynamic_response_middlewares is None else self._dynamic_response_middlewares()
        for middleware in (*self._response_middlewares, *dynamic_response):
            final_response = middleware.process_response(exchange.request, final_response)

        if self._traffic_rule_evaluator is not None:
            final_response = self._traffic_rule_evaluator.process_response(
                exchange.request, final_response, request_id=exchange.request_id
            )

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
