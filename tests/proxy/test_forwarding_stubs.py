import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from proxyscope.app.config.runtime import RuntimeConfig, set_runtime_config
from proxyscope.proxy.forwarding import ForwardRequest, UpstreamForwarder


class TestForwardingStubs(unittest.TestCase):
    def tearDown(self) -> None:
        set_runtime_config(RuntimeConfig())

    def test_forwarder_contract_with_upstream_server(self) -> None:
        class UpstreamHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.server.last_path = self.path  # type: ignore[attr-defined]
                self.server.last_body = body  # type: ignore[attr-defined]
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"upstream":"ok"}')

            def log_message(self, fmt: str, *args: object) -> None:
                return

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()

        host, port = upstream.server_address
        forwarder = UpstreamForwarder()
        request = ForwardRequest(
            method="POST",
            path="/users",
            headers={
                "Host": f"{host}:{port}",
                "Content-Type": "application/json",
            },
            body=b'{"name":"tim"}',
        )

        try:
            response = forwarder.forward(request)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.body, b'{"upstream":"ok"}')
            self.assertEqual(upstream.last_path, "/users")  # type: ignore[attr-defined]
            self.assertEqual(upstream.last_body, b'{"name":"tim"}')  # type: ignore[attr-defined]
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=2)

    def test_forwarder_requires_host_for_origin_form_paths(self) -> None:
        forwarder = UpstreamForwarder()
        request = ForwardRequest(
            method="GET",
            path="/health",
            headers={},
            body=b"",
        )
        with self.assertRaises(ValueError):
            forwarder.forward(request)

    def test_forwarder_applies_cache_invalidation_headers(self) -> None:
        class UpstreamHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.server.last_path = self.path  # type: ignore[attr-defined]
                self.server.last_headers = dict(self.headers.items())  # type: ignore[attr-defined]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, fmt: str, *args: object) -> None:
                return

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()

        host, port = upstream.server_address
        config = RuntimeConfig(cache_invalidation_enabled=True)
        set_runtime_config(config)

        forwarder = UpstreamForwarder()
        request = ForwardRequest(
            method="GET",
            path="/cache",
            headers={
                "Host": f"{host}:{port}",
                "If-None-Match": '"etag-123"',
                "If-Modified-Since": "Mon, 01 Jan 2024 00:00:00 GMT",
            },
            body=b"",
        )

        try:
            response = forwarder.forward(request)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(upstream.last_path, "/cache")  # type: ignore[attr-defined]
            upstream_headers = {key.lower(): value for key, value in upstream.last_headers.items()}  # type: ignore[attr-defined]
            self.assertNotIn("if-none-match", upstream_headers)
            self.assertNotIn("if-modified-since", upstream_headers)
            self.assertEqual(upstream_headers.get("cache-control"), "no-cache, no-store, max-age=0, must-revalidate")
            self.assertEqual(upstream_headers.get("pragma"), "no-cache")
            self.assertEqual(upstream_headers.get("expires"), "0")
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=2)
