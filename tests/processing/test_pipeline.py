import unittest
from dataclasses import replace

from proxyscope.processing.middleware import CacheInvalidationMiddleware
from proxyscope.processing.models import ExchangeRequest, ExchangeResponse
from proxyscope.processing.pipeline import ExchangePipeline


class _PolicyEvaluator:
    def __init__(self, *, static_response: ExchangeResponse | None = None, transform: bool = False) -> None:
        self.static_response = static_response
        self.transform = transform

    def should_modify_response_for_request(self, *, method: str, url: str) -> bool:
        return self.transform

    def get_static_response_template_for_request(self, *, method: str, url: str) -> ExchangeResponse | None:
        return self.static_response


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.responses: list[ExchangeResponse] = []

    def record_request(self, **request: object) -> int:
        self.requests.append(request)
        return len(self.requests)

    def record_response(
        self,
        response: ExchangeResponse,
        *,
        request_id: int | None,
        duration_ms: float,
        client_ip: str,
        target_host: str | None = None,
    ) -> None:
        self.responses.append(response)


class _Transformer:
    def __init__(self) -> None:
        self.calls = 0

    def maybe_modify_response(
        self,
        *,
        request_url: str,
        method: str,
        response: ExchangeResponse,
    ) -> ExchangeResponse:
        self.calls += 1
        return replace(response, body=b"edited")


class _Events:
    def __init__(self) -> None:
        self.hosts: list[str] = []

    def on_site_visit(self, host: str) -> None:
        self.hosts.append(host)


class _CachePolicy:
    cache_invalidation_enabled = True


class _RequestMiddleware:
    def __init__(self) -> None:
        self.protocols: list[str] = []

    def process_request(self, request: ExchangeRequest) -> ExchangeRequest:
        self.protocols.append(request.protocol)
        return replace(request, headers={**request.headers, "X-Middleware": "request"})


class _ResponseMiddleware:
    def __init__(self) -> None:
        self.protocols: list[str] = []

    def process_response(self, request: ExchangeRequest, response: ExchangeResponse) -> ExchangeResponse:
        self.protocols.append(request.protocol)
        return replace(response, headers={**response.headers, "X-Middleware": "response"})


class TestExchangePipeline(unittest.TestCase):
    def test_http_and_mitm_use_the_same_pipeline_steps(self) -> None:
        recorder = _Recorder()
        transformer = _Transformer()
        events = _Events()
        request_middleware = _RequestMiddleware()
        response_middleware = _ResponseMiddleware()
        pipeline = ExchangePipeline(
            policy_evaluator=_PolicyEvaluator(transform=True),
            exchange_recorder=recorder,
            response_transformer=transformer,
            runtime_events=events,
            cache_middleware=CacheInvalidationMiddleware(_CachePolicy()),
            request_middlewares=[request_middleware],
            response_middlewares=[response_middleware],
        )

        for protocol in ("http", "https-mitm"):
            with self.subTest(protocol=protocol):
                exchange = pipeline.prepare_request(
                    ExchangeRequest(
                        method="GET",
                        url="https://example.com/demo",
                        path="/demo",
                        headers={"Host": "example.com", "If-None-Match": '"etag"'},
                        target_host="example.com",
                        protocol=protocol,
                    )
                )
                response = pipeline.process_response(
                    exchange,
                    ExchangeResponse(200, "OK", {"Content-Type": "text/plain"}, b"upstream"),
                    duration_ms=1.0,
                )

                self.assertNotIn("If-None-Match", exchange.request.headers)
                self.assertEqual(exchange.request.headers["X-Middleware"], "request")
                self.assertTrue(exchange.requires_buffered_response)
                self.assertEqual(response.body, b"edited")
                self.assertEqual(response.headers["X-Middleware"], "response")

        self.assertEqual(request_middleware.protocols, ["http", "https-mitm"])
        self.assertEqual(response_middleware.protocols, ["http", "https-mitm"])
        self.assertEqual(transformer.calls, 2)
        self.assertEqual(events.hosts, ["example.com", "example.com"])
        self.assertEqual(len(recorder.requests), 2)
        self.assertEqual(len(recorder.responses), 2)

    def test_static_response_takes_precedence_over_transformer(self) -> None:
        static_response = ExchangeResponse(202, "Accepted", {"Content-Type": "text/plain"}, b"static")
        transformer = _Transformer()
        recorder = _Recorder()
        pipeline = ExchangePipeline(
            policy_evaluator=_PolicyEvaluator(static_response=static_response, transform=True),
            exchange_recorder=recorder,
            response_transformer=transformer,
            runtime_events=_Events(),
            cache_middleware=CacheInvalidationMiddleware(_CachePolicy()),
        )
        exchange = pipeline.prepare_request(
            ExchangeRequest(method="GET", url="http://example.com/demo", path="/demo", headers={})
        )

        response = pipeline.process_response(
            exchange,
            ExchangeResponse(500, "Upstream", {}, b"upstream"),
            duration_ms=1.0,
        )

        self.assertEqual(response.body, b"static")
        self.assertEqual(transformer.calls, 0)
        self.assertEqual(recorder.responses, [response])


if __name__ == "__main__":
    unittest.main()
