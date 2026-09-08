import socket
import ssl
import unittest
from unittest.mock import Mock, patch

from proxyscope.adapters.mitm.tunnel import (
    MitmTLSInterceptor,
    _build_https_request_url,
    _parse_request_start_line,
    _relay_tls_bidirectional,
)
from proxyscope.adapters.proxy.connect.tunnel import (
    ConnectTarget,
    ConnectUpstreamConnectionError,
    ConnectUpstreamTimeoutError,
)
from proxyscope.application.journal import RequestJournal
from proxyscope.bootstrap.composition import create_proxy_runtime_context
from tests.support.runtime_context import RuntimeTestContext, processing_dependencies


class _FakeSocket:
    def __init__(self, recv_values: list[bytes | Exception]) -> None:
        self._recv_values = list(recv_values)
        self.sent: list[bytes] = []
        self.timeouts: list[float] = []
        self.shutdown_calls: int = 0

    def __enter__(self) -> "_FakeSocket":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        return

    def recv(self, _size: int) -> bytes:
        if not self._recv_values:
            return b""
        value = self._recv_values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def settimeout(self, timeout_s: float) -> None:
        self.timeouts.append(timeout_s)

    def shutdown(self, _how: int) -> None:
        self.shutdown_calls += 1

    def close(self) -> None:
        return

    def getpeername(self) -> tuple[str, int]:
        return ("127.0.0.1", 12345)


class _IdentityRewriter:
    def __init__(self) -> None:
        self.flushed = False

    def feed(self, data: bytes) -> bytes:
        return data

    def flush(self) -> bytes:
        self.flushed = True
        return b""


class TestMitmTunnelHelpers(unittest.TestCase):
    def test_parse_request_start_line(self) -> None:
        self.assertEqual(_parse_request_start_line("POST /api HTTP/1.1"), ("POST", "/api"))
        self.assertEqual(_parse_request_start_line("bad-start-line"), ("GET", "/"))

    def test_build_https_request_url(self) -> None:
        self.assertEqual(
            _build_https_request_url(host="example.com", port=443, path="/hello"),
            "https://example.com/hello",
        )
        self.assertEqual(
            _build_https_request_url(host="example.com", port=8443, path="hello"),
            "https://example.com:8443/hello",
        )
        self.assertEqual(
            _build_https_request_url(host="example.com", port=443, path="https://already/absolute"),
            "https://already/absolute",
        )


class TestMitmRelay(unittest.TestCase):
    def test_relay_forwards_client_to_upstream(self) -> None:
        client_tls = _FakeSocket([b"GET / HTTP/1.1\r\n\r\n", b""])
        upstream_tls = _FakeSocket([b""])
        request_sniffer = Mock()
        response_sniffer = Mock()
        response_rewriter = _IdentityRewriter()

        with patch("proxyscope.adapters.mitm.tunnel.HTTP1RequestHeaderRewriter", return_value=_IdentityRewriter()):
            _relay_tls_bidirectional(
                client_tls,  # type: ignore[arg-type]
                upstream_tls,  # type: ignore[arg-type]
                timeout_s=0.2,
                request_sniffer=request_sniffer,
                response_sniffer=response_sniffer,
                response_rewriter=response_rewriter,  # type: ignore[arg-type]
                rewrite_request_headers=lambda headers: headers,
            )

        self.assertEqual(upstream_tls.sent, [b"GET / HTTP/1.1\r\n\r\n"])
        request_sniffer.feed.assert_called()
        self.assertGreaterEqual(client_tls.shutdown_calls, 1)
        self.assertGreaterEqual(upstream_tls.shutdown_calls, 1)

    def test_relay_raises_non_transport_errors(self) -> None:
        client_tls = _FakeSocket([ValueError("boom")])
        upstream_tls = _FakeSocket([b""])
        request_sniffer = Mock()
        response_sniffer = Mock()
        response_rewriter = _IdentityRewriter()

        with self.assertRaises(ValueError):
            _relay_tls_bidirectional(
                client_tls,  # type: ignore[arg-type]
                upstream_tls,  # type: ignore[arg-type]
                timeout_s=0.2,
                request_sniffer=request_sniffer,
                response_sniffer=response_sniffer,
                response_rewriter=response_rewriter,  # type: ignore[arg-type]
                rewrite_request_headers=None,
            )

    def test_relay_ignores_transport_errors(self) -> None:
        client_tls = _FakeSocket([OSError("broken pipe")])
        upstream_tls = _FakeSocket([b""])
        request_sniffer = Mock()
        response_sniffer = Mock()
        response_rewriter = _IdentityRewriter()

        _relay_tls_bidirectional(
            client_tls,  # type: ignore[arg-type]
            upstream_tls,  # type: ignore[arg-type]
            timeout_s=0.2,
            request_sniffer=request_sniffer,
            response_sniffer=response_sniffer,
            response_rewriter=response_rewriter,  # type: ignore[arg-type]
            rewrite_request_headers=None,
        )

    def test_relay_re_raises_connect_timeout_errors(self) -> None:
        client_tls = _FakeSocket([ConnectUpstreamTimeoutError("timeout")])
        upstream_tls = _FakeSocket([b""])
        request_sniffer = Mock()
        response_sniffer = Mock()
        response_rewriter = _IdentityRewriter()

        with self.assertRaises(ConnectUpstreamTimeoutError):
            _relay_tls_bidirectional(
                client_tls,  # type: ignore[arg-type]
                upstream_tls,  # type: ignore[arg-type]
                timeout_s=0.2,
                request_sniffer=request_sniffer,
                response_sniffer=response_sniffer,
                response_rewriter=response_rewriter,  # type: ignore[arg-type]
                rewrite_request_headers=None,
            )

    def test_relay_ignores_ssl_errors(self) -> None:
        client_tls = _FakeSocket([ssl.SSLError("EOF occurred in violation of protocol")])
        upstream_tls = _FakeSocket([b""])
        request_sniffer = Mock()
        response_sniffer = Mock()
        response_rewriter = _IdentityRewriter()

        _relay_tls_bidirectional(
            client_tls,  # type: ignore[arg-type]
            upstream_tls,  # type: ignore[arg-type]
            timeout_s=0.2,
            request_sniffer=request_sniffer,
            response_sniffer=response_sniffer,
            response_rewriter=response_rewriter,  # type: ignore[arg-type]
            rewrite_request_headers=None,
        )


class TestMitmTLSInterceptor(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime_context = create_proxy_runtime_context(
            **processing_dependencies(RuntimeTestContext()),
            request_journal=RequestJournal(),
        )

    def test_intercept_raises_timeout_for_upstream_connect_timeout(self) -> None:
        certificate_authority = Mock()
        certificate_authority.issue_host_certificate.return_value = ("cert.pem", "key.pem")
        interceptor = MitmTLSInterceptor(certificate_authority=certificate_authority, runtime_context=self.runtime_context)
        client = _FakeSocket([])
        client_tls = _FakeSocket([b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"])
        client_ctx = Mock()
        client_ctx.wrap_socket.return_value = client_tls

        with (
            patch("proxyscope.adapters.mitm.tunnel.socket.create_connection", side_effect=socket.timeout),
            patch("proxyscope.adapters.mitm.tunnel.ssl.SSLContext", return_value=client_ctx),
        ):
            with self.assertRaises(ConnectUpstreamTimeoutError):
                interceptor.intercept(
                    client_socket=client,  # type: ignore[arg-type]
                    target=ConnectTarget(host="example.com", port=443),
                    timeout_s=0.1,
                )

    def test_intercept_raises_connection_error_for_upstream_connect_failure(self) -> None:
        certificate_authority = Mock()
        certificate_authority.issue_host_certificate.return_value = ("cert.pem", "key.pem")
        interceptor = MitmTLSInterceptor(certificate_authority=certificate_authority, runtime_context=self.runtime_context)
        client = _FakeSocket([])
        client_tls = _FakeSocket([b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"])
        client_ctx = Mock()
        client_ctx.wrap_socket.return_value = client_tls

        with (
            patch("proxyscope.adapters.mitm.tunnel.socket.create_connection", side_effect=OSError("no route")),
            patch("proxyscope.adapters.mitm.tunnel.ssl.SSLContext", return_value=client_ctx),
        ):
            with self.assertRaises(ConnectUpstreamConnectionError):
                interceptor.intercept(
                    client_socket=client,  # type: ignore[arg-type]
                    target=ConnectTarget(host="example.com", port=443),
                    timeout_s=0.1,
                )

    def test_intercept_raises_connection_error_for_upstream_tls_failure(self) -> None:
        certificate_authority = Mock()
        certificate_authority.issue_host_certificate.return_value = ("cert.pem", "key.pem")
        interceptor = MitmTLSInterceptor(certificate_authority=certificate_authority, runtime_context=self.runtime_context)
        client = _FakeSocket([])
        client_tls = _FakeSocket([b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"])
        upstream_tcp = _FakeSocket([])
        upstream_ctx = Mock()
        upstream_ctx.wrap_socket.side_effect = ssl.SSLError("bad tls")
        client_ctx = Mock()
        client_ctx.wrap_socket.return_value = client_tls

        with (
            patch("proxyscope.adapters.mitm.tunnel.socket.create_connection", return_value=upstream_tcp),
            patch("proxyscope.adapters.mitm.tunnel.ssl.create_default_context", return_value=upstream_ctx),
            patch("proxyscope.adapters.mitm.tunnel.ssl.SSLContext", return_value=client_ctx),
        ):
            with self.assertRaises(ConnectUpstreamConnectionError):
                interceptor.intercept(
                    client_socket=client,  # type: ignore[arg-type]
                    target=ConnectTarget(host="example.com", port=443),
                    timeout_s=0.1,
                )

    def test_intercept_returns_false_when_client_rejects_forged_certificate(self) -> None:
        certificate_authority = Mock()
        certificate_authority.issue_host_certificate.return_value = ("cert.pem", "key.pem")
        interceptor = MitmTLSInterceptor(
            certificate_authority=certificate_authority,
            runtime_context=self.runtime_context,
        )
        client = _FakeSocket([])
        upstream_tcp = _FakeSocket([])
        upstream_tls = _FakeSocket([])

        upstream_ctx = Mock()
        upstream_ctx.wrap_socket.return_value = upstream_tls
        client_ctx = Mock()
        client_ctx.wrap_socket.side_effect = ssl.SSLError("untrusted cert")

        with (
            patch("proxyscope.adapters.mitm.tunnel.socket.create_connection", return_value=upstream_tcp),
            patch("proxyscope.adapters.mitm.tunnel.ssl.create_default_context", return_value=upstream_ctx),
            patch("proxyscope.adapters.mitm.tunnel.ssl.SSLContext", return_value=client_ctx),
        ):
            ok = interceptor.intercept(
                client_socket=client,  # type: ignore[arg-type]
                target=ConnectTarget(host="example.com", port=443),
                timeout_s=0.1,
            )

        self.assertFalse(ok)
        self.assertEqual(client.sent, [b"HTTP/1.1 200 Connection Established\r\n\r\n"])
        certificate_authority.issue_host_certificate.assert_called_once_with("example.com")

    def test_intercept_runs_relay_and_returns_true(self) -> None:
        certificate_authority = Mock()
        certificate_authority.issue_host_certificate.return_value = ("cert.pem", "key.pem")
        interceptor = MitmTLSInterceptor(
            certificate_authority=certificate_authority,
            runtime_context=self.runtime_context,
        )
        client = _FakeSocket([])
        upstream_tcp = _FakeSocket([])
        upstream_tls = _FakeSocket([])
        client_tls = _FakeSocket([b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"])

        upstream_ctx = Mock()
        upstream_ctx.wrap_socket.return_value = upstream_tls
        client_ctx = Mock()
        client_ctx.wrap_socket.return_value = client_tls

        with (
            patch("proxyscope.adapters.mitm.tunnel.socket.create_connection", return_value=upstream_tcp),
            patch("proxyscope.adapters.mitm.tunnel.ssl.create_default_context", return_value=upstream_ctx),
            patch("proxyscope.adapters.mitm.tunnel.ssl.SSLContext", return_value=client_ctx),
            patch("proxyscope.adapters.mitm.tunnel._relay_tls_bidirectional") as relay_mock,
        ):
            ok = interceptor.intercept(
                client_socket=client,  # type: ignore[arg-type]
                target=ConnectTarget(host="example.com", port=443),
                timeout_s=0.1,
            )

        self.assertTrue(ok)
        relay_mock.assert_called_once()
        certificate_authority.issue_host_certificate.assert_called_once_with("example.com")
        client_ctx.load_cert_chain.assert_called_once_with(certfile="cert.pem", keyfile="key.pem")

    def test_intercept_serves_https_static_response_without_an_upstream_connection(self) -> None:
        config = RuntimeTestContext()
        config.add_static_response_rule(
            url="https://example.com/health",
            status_code=503,
            reason="Service Unavailable",
            headers={"Content-Type": "text/plain"},
            body=b"offline",
            method="GET",
        )
        runtime_context = create_proxy_runtime_context(
            **processing_dependencies(config),
            request_journal=RequestJournal(),
        )
        certificate_authority = Mock()
        certificate_authority.issue_host_certificate.return_value = ("cert.pem", "key.pem")
        interceptor = MitmTLSInterceptor(certificate_authority=certificate_authority, runtime_context=runtime_context)
        client = _FakeSocket([])
        client_tls = _FakeSocket([b"GET /health HTTP/1.1\r\nHost: example.com\r\n\r\n"])
        client_ctx = Mock()
        client_ctx.wrap_socket.return_value = client_tls

        with (
            patch("proxyscope.adapters.mitm.tunnel.ssl.SSLContext", return_value=client_ctx),
            patch("proxyscope.adapters.mitm.tunnel.socket.create_connection") as connect,
        ):
            ok = interceptor.intercept(
                client_socket=client,  # type: ignore[arg-type]
                target=ConnectTarget(host="example.com", port=443),
                timeout_s=0.1,
            )

        self.assertTrue(ok)
        connect.assert_not_called()
        self.assertEqual(client_tls.sent, [b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: text/plain\r\nContent-Length: 7\r\n\r\noffline"])
