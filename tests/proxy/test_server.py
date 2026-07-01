import http.client
import socket
import socketserver
import threading
import time
import unittest

from proxyscope.app.composition import create_proxy_runtime_context
from proxyscope.application.journal import RequestJournal
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.processing.ports import ForwardRequest, ForwardResponse
from proxyscope.proxy.server import create_server
from tests.support.runtime_context import RuntimeTestContext, processing_dependencies


class StaticForwarder:
    def forward(self, request: ForwardRequest) -> ForwardResponse:
        body = b"Milestone 1: request received and logged\n"
        return ForwardResponse(
            status_code=200,
            reason="OK",
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Content-Length": str(len(body)),
            },
            body=body,
        )


class _CountingModifier:
    def __init__(self) -> None:
        self.calls = 0

    def maybe_modify_response(self, *, request_url: str, method: str, response: ForwardResponse) -> ForwardResponse:
        self.calls += 1
        return response


class TestRequestLoggingServer(unittest.TestCase):
    def setUp(self) -> None:
        self.config = RuntimeTestContext()
        self.journal = RequestJournal()
        self.modifier = ResponseModifierService()
        self.runtime_context = create_proxy_runtime_context(
            **processing_dependencies(self.config),
            request_journal=self.journal,
            response_modifier=self.modifier,
        )
        self.server = create_server(
            "127.0.0.1",
            0,
            runtime_context=self.runtime_context,
            forwarder=StaticForwarder(),
            auto_enable_mitm=False,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _request(
        self, method: str, path: str, *, headers: dict[str, str] | None = None, body: bytes | None = None
    ) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=2)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        status = response.status
        data = response.read()
        conn.close()
        return status, data

    def test_get_returns_200_and_body(self) -> None:
        status, data = self._request("GET", "/hello")
        self.assertEqual(status, 200)
        self.assertEqual(data, b"Milestone 1: request received and logged\n")

    def test_head_returns_200_without_body(self) -> None:
        status, data = self._request("HEAD", "/hello")
        self.assertEqual(status, 200)
        self.assertEqual(data, b"")

    def test_connect_establishes_tunnel_and_relays_bytes(self) -> None:
        class EchoHandler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                while True:
                    data = self.request.recv(65536)
                    if not data:
                        return
                    self.request.sendall(data)

        echo_server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), EchoHandler)
        echo_thread = threading.Thread(target=echo_server.serve_forever, daemon=True)
        echo_thread.start()

        try:
            echo_host, echo_port = echo_server.server_address
            with socket.create_connection((self.host, self.port), timeout=2) as proxy_client:
                connect_request = (
                    f"CONNECT {echo_host}:{echo_port} HTTP/1.1\r\nHost: {echo_host}:{echo_port}\r\n\r\n"
                ).encode("utf-8")
                proxy_client.sendall(connect_request)

                response_head = b""
                while b"\r\n\r\n" not in response_head:
                    chunk = proxy_client.recv(4096)
                    if not chunk:
                        break
                    response_head += chunk

                self.assertIn(b"200 Connection Established", response_head)

                payload = b"ping through connect tunnel"
                proxy_client.sendall(payload)
                echoed = proxy_client.recv(len(payload))
                self.assertEqual(echoed, payload)
        finally:
            echo_server.shutdown()
            echo_server.server_close()
            echo_thread.join(timeout=2)

    def test_connect_invalid_target_returns_400(self) -> None:
        status, data = self._request("CONNECT", "https://example.com:443")
        self.assertEqual(status, 400)
        self.assertIn(b"Invalid CONNECT target:", data)

    def test_request_is_logged(self) -> None:
        with self.assertLogs("pscope.request", level="INFO") as captured:
            self._request("GET", "/log-test", headers={"X-Demo": "m1"})

        logs = "\n".join(captured.output)
        self.assertIn("Incoming request method=GET path=/log-test", logs)

    def test_response_is_logged_for_forwarded_request(self) -> None:
        class DummyForwarder:
            def forward(self, request: ForwardRequest) -> ForwardResponse:
                return ForwardResponse(
                    status_code=204,
                    reason="No Content",
                    headers={"X-Upstream": "demo"},
                    body=b"",
                )

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

        self.server = create_server(
            "127.0.0.1",
            0,
            runtime_context=self.runtime_context,
            forwarder=DummyForwarder(),
            auto_enable_mitm=False,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

        with self.assertLogs("pscope.response", level="INFO") as captured:
            status, _ = self._request("GET", "/response-log-test")
            time.sleep(0.05)

        self.assertEqual(status, 204)
        logs = "\n".join(captured.output)
        self.assertIn("Outgoing response status=204 reason=No Content", logs)

    def test_server_can_use_forwarder(self) -> None:
        class DummyForwarder:
            def __init__(self) -> None:
                self.last_request: ForwardRequest | None = None

            def forward(self, request: ForwardRequest) -> ForwardResponse:
                self.last_request = request
                return ForwardResponse(
                    status_code=202,
                    reason="Accepted",
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                    body=b"forwarded",
                )

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

        forwarder = DummyForwarder()
        self.server = create_server(
            "127.0.0.1",
            0,
            runtime_context=self.runtime_context,
            forwarder=forwarder,
            auto_enable_mitm=False,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

        status, data = self._request(
            "POST",
            "/forward-me",
            headers={"Content-Type": "application/json"},
            body=b'{"ok":true}',
        )

        self.assertEqual(status, 202)
        self.assertEqual(data, b"forwarded")
        self.assertIsNotNone(forwarder.last_request)
        mapped_request = forwarder.last_request
        assert mapped_request is not None
        self.assertEqual(mapped_request.path, "/forward-me")
        self.assertEqual(mapped_request.body, b'{"ok":true}')

    def test_static_response_policy_skips_upstream_forwarder(self) -> None:
        class CountingForwarder:
            def __init__(self) -> None:
                self.calls = 0

            def forward(self, request: ForwardRequest) -> ForwardResponse:
                self.calls += 1
                return ForwardResponse(
                    status_code=500,
                    reason="ShouldNotBeUsed",
                    headers={"Content-Type": "text/plain"},
                    body=b"upstream",
                )

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

        config = RuntimeTestContext()
        config.add_static_response_rule(
            url="http://example.com/mock",
            status_code=200,
            reason="OK",
            headers={"Content-Type": "application/json"},
            body=b'{"source":"policy"}',
            method="GET",
        )
        self.runtime_context = create_proxy_runtime_context(
            **processing_dependencies(config),
            request_journal=self.journal,
        )

        forwarder = CountingForwarder()
        self.server = create_server(
            "127.0.0.1",
            0,
            runtime_context=self.runtime_context,
            forwarder=forwarder,
            auto_enable_mitm=False,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

        status, data = self._request(
            "GET",
            "http://example.com/mock",
            headers={"Host": "example.com"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data, b'{"source":"policy"}')
        self.assertEqual(forwarder.calls, 0)

    def test_static_response_policy_skips_editor_modifier(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

        config = RuntimeTestContext()
        config.add_open_editor_policy("http://example.com/mock", method="GET")
        config.add_static_response_rule(
            url="http://example.com/mock",
            status_code=200,
            reason="OK",
            headers={"Content-Type": "application/json"},
            body=b'{"source":"policy"}',
            method="GET",
        )
        modifier = _CountingModifier()
        self.runtime_context = create_proxy_runtime_context(
            **processing_dependencies(config),
            request_journal=self.journal,
            response_modifier=modifier,  # type: ignore[arg-type]
        )
        self.server = create_server(
            "127.0.0.1",
            0,
            runtime_context=self.runtime_context,
            forwarder=StaticForwarder(),
            auto_enable_mitm=False,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

        status, data = self._request(
            "GET",
            "http://example.com/mock",
            headers={"Host": "example.com"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data, b'{"source":"policy"}')
        self.assertEqual(modifier.calls, 0)

    def test_streams_large_upstream_response_with_truncated_preview(self) -> None:
        class UpstreamHandler(socketserver.BaseRequestHandler):
            response_body = b"x" * 5000

            def handle(self) -> None:
                request_data = b""
                while b"\r\n\r\n" not in request_data:
                    chunk = self.request.recv(4096)
                    if not chunk:
                        return
                    request_data += chunk
                response = (
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 5000\r\n\r\n" + self.response_body
                )
                self.request.sendall(response)

        upstream = socketserver.ThreadingTCPServer(("127.0.0.1", 0), UpstreamHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

        self.server = create_server(
            "127.0.0.1",
            0,
            runtime_context=self.runtime_context,
            auto_enable_mitm=False,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

        try:
            upstream_host, upstream_port = upstream.server_address
            status, data = self._request(
                "GET",
                f"http://{upstream_host}:{upstream_port}/large",
                headers={"Host": f"{upstream_host}:{upstream_port}"},
            )

            self.assertEqual(status, 200)
            self.assertEqual(data, UpstreamHandler.response_body)

            entry = None
            for _ in range(10):
                entries = self.journal.list_entries()
                if entries and entries[-1].response is not None:
                    entry = entries[-1]
                    break
                time.sleep(0.01)
            self.assertIsNotNone(entry)
            assert entry is not None
            assert entry.response is not None
            self.assertEqual(entry.response.body_size, 5000)
            self.assertTrue(entry.response.body_preview.endswith("...[truncated 904 bytes]"))
        finally:
            upstream.shutdown()
            upstream.server_close()
            upstream_thread.join(timeout=2)
