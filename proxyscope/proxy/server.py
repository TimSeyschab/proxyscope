import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from proxyscope.mitm.certificates import MitmCertificateError, certificate_authority_for_root, default_ca
from proxyscope.mitm.tunnel import MitmTLSInterceptor
from proxyscope.processing.models import ExchangeRequest
from proxyscope.processing.ports import (
    BODY_PREVIEW_BYTES,
    STREAM_CHUNK_SIZE,
    Forwarder,
    ForwardRequest,
    ForwardResponse,
    StreamingForwarder,
    capture_body_preview,
)
from proxyscope.proxy.connect_tunnel import (
    ConnectUpstreamConnectionError,
    ConnectUpstreamTimeoutError,
    handle_connect_tunnel,
    parse_connect_target,
)
from proxyscope.proxy.forwarding import UpstreamForwarder, prepare_forward_request, resolve_target_url
from proxyscope.proxy.http_bridge import map_incoming_request, write_forward_response
from proxyscope.proxy.runtime import ProxyRuntimeContext
from proxyscope.proxy.tunnel_registry import TunnelConnectionRegistry

SERVER_LOGGER: Final = logging.getLogger("pscope.server")


class ProxyHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        forwarder: Forwarder,
        runtime_context: ProxyRuntimeContext,
        mitm_interceptor: MitmTLSInterceptor | None = None,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.forwarder = forwarder
        self.runtime_context = runtime_context
        self.mitm_interceptor = mitm_interceptor
        self._tunnel_registry = TunnelConnectionRegistry()

    def register_tunnel_socket(self, sock: object) -> None:
        self._tunnel_registry.register(sock)

    def unregister_tunnel_socket(self, sock: object) -> None:
        self._tunnel_registry.unregister(sock)

    def close_all_active_tunnels(self) -> int:
        return self._tunnel_registry.close_all()


class RequestLoggingHandler(BaseHTTPRequestHandler):
    server_version = "pscope/0.1"

    def _send_connect_error_response(self, *, status: int, reason: str, body: bytes) -> None:
        """
        Best-effort HTTP error response for CONNECT setup failures.
        """
        try:
            self.send_response(status, reason)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            # Connection may already be closed or switched out of HTTP framing.
            SERVER_LOGGER.debug("Could not write CONNECT error response; socket no longer writable.")

    def _log_connect_outcome(
        self,
        *,
        request_id: int | None,
        started: float,
        target_host: str | None,
        status_code: int,
        reason: str,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        duration_ms = (time.perf_counter() - started) * 1000
        response_headers = dict(headers or {})
        server = self.server
        if not isinstance(server, ProxyHTTPServer):
            return
        server.runtime_context.exchange_recorder.record_response(
            ForwardResponse(
                status_code=status_code,
                reason=reason,
                headers=response_headers,
                body=body,
            ),
            request_id=request_id,
            duration_ms=duration_ms,
            client_ip=self.client_address[0],
            target_host=target_host,
        )

    def _respond_connect_error_and_log(
        self,
        *,
        request_id: int | None,
        started: float,
        target_host: str | None,
        status: int,
        reason: str,
        body: bytes,
    ) -> None:
        self._send_connect_error_response(status=status, reason=reason, body=body)
        self._log_connect_outcome(
            request_id=request_id,
            started=started,
            target_host=target_host,
            status_code=status,
            reason=reason,
            body=body,
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Content-Length": str(len(body)),
            },
        )

    def _forward_upstream_streaming(
        self,
        forwarder: StreamingForwarder,
        request: ForwardRequest,
        *,
        send_body: bool,
    ) -> ForwardResponse:
        upstream_response = forwarder.open_stream(request)
        try:
            self.send_response(upstream_response.status_code, upstream_response.reason)
            for name, value in upstream_response.headers.items():
                self.send_header(name, value)
            self.end_headers()

            preview = b""
            body_size = 0
            if send_body:

                def write_chunk(chunk: bytes) -> None:
                    self.wfile.write(chunk)

                preview, body_size = capture_body_preview(
                    upstream_response.iter_body_chunks(STREAM_CHUNK_SIZE),
                    max_bytes=BODY_PREVIEW_BYTES,
                    on_chunk=write_chunk,
                )

            return ForwardResponse(
                status_code=upstream_response.status_code,
                reason=upstream_response.reason,
                headers=dict(upstream_response.headers),
                body=preview,
                body_size=body_size,
            )
        finally:
            upstream_response.close()

    def _handle(self, *, send_body: bool) -> None:
        started = time.perf_counter()
        server = self.server
        if not isinstance(server, ProxyHTTPServer):
            self.send_error(500, "Server misconfiguration")
            return

        forward_request = map_incoming_request(self)
        forward_request = prepare_forward_request(forward_request)
        target_host, target_port = _resolve_forward_request_target(forward_request)
        try:
            target_url = resolve_target_url(forward_request)
        except ValueError as exc:
            request_id = server.runtime_context.exchange_recorder.record_request(
                method=self.command,
                path=forward_request.path,
                client_ip=self.client_address[0],
                headers=forward_request.headers,
                body=forward_request.body,
                target_host=target_host,
                target_port=target_port,
            )
            error_body = f"{exc}\n".encode("utf-8")
            self.send_response(400, "Bad Request")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(error_body)))
            self.end_headers()
            if send_body:
                self.wfile.write(error_body)
            duration_ms = (time.perf_counter() - started) * 1000
            server.runtime_context.exchange_recorder.record_response(
                ForwardResponse(
                    status_code=400,
                    reason="Bad Request",
                    headers={
                        "Content-Type": "text/plain; charset=utf-8",
                        "Content-Length": str(len(error_body)),
                    },
                    body=error_body,
                ),
                request_id=request_id,
                duration_ms=duration_ms,
                client_ip=self.client_address[0],
                target_host=target_host,
            )
            return

        exchange = server.runtime_context.exchange_pipeline.prepare_request(
            ExchangeRequest(
                method=self.command,
                url=target_url,
                path=forward_request.path,
                headers=forward_request.headers,
                body=forward_request.body,
                client_ip=self.client_address[0],
                target_host=target_host,
                target_port=target_port,
            )
        )
        forward_request = ForwardRequest(
            method=exchange.request.method,
            path=exchange.request.path,
            headers=exchange.request.headers,
            body=exchange.request.body,
        )
        if exchange.static_response is not None:
            forward_response = server.runtime_context.exchange_pipeline.process_response(
                exchange,
                exchange.static_response,
            )
        elif isinstance(server.forwarder, StreamingForwarder) and not exchange.requires_buffered_response:
            forward_response = self._forward_upstream_streaming(
                server.forwarder,
                forward_request,
                send_body=send_body,
            )
            server.runtime_context.exchange_pipeline.process_response(
                exchange,
                forward_response,
            )
            return
        else:
            forward_response = server.forwarder.forward(forward_request)
            forward_response = server.runtime_context.exchange_pipeline.process_response(exchange, forward_response)
        write_forward_response(self, forward_response, send_body=send_body)

    def do_GET(self) -> None:
        self._handle(send_body=True)

    def do_POST(self) -> None:
        self._handle(send_body=True)

    def do_PUT(self) -> None:
        self._handle(send_body=True)

    def do_PATCH(self) -> None:
        self._handle(send_body=True)

    def do_DELETE(self) -> None:
        self._handle(send_body=True)

    def do_OPTIONS(self) -> None:
        self._handle(send_body=True)

    def do_HEAD(self) -> None:
        self._handle(send_body=False)

    def do_CONNECT(self) -> None:
        started = time.perf_counter()
        target_host: str | None = None
        target_port: int | None = None
        request_id: int | None = None
        try:
            target = parse_connect_target(self.path)
            target_host = target.host
            target_port = target.port
            server = self.server
            if not isinstance(server, ProxyHTTPServer):
                self.send_error(500, "Server misconfiguration")
                return
            request_id = server.runtime_context.exchange_recorder.record_request(
                method=self.command,
                path=self.path,
                client_ip=self.client_address[0],
                headers={name: value for name, value in self.headers.items()},
                body=b"",
                target_host=target_host,
                target_port=target_port,
            )
            server.runtime_context.runtime_events.on_site_visit(target.host)
            server.register_tunnel_socket(self.connection)

            if server.mitm_interceptor is not None:
                tunnel_established = server.mitm_interceptor.intercept(
                    client_socket=self.connection,
                    target=target,
                    timeout_s=30.0,
                )
                if not tunnel_established:
                    SERVER_LOGGER.warning(
                        "MITM client TLS handshake failed target=%s:%d client=%s",
                        target.host,
                        target.port,
                        self.client_address[0],
                    )
                    self._log_connect_outcome(
                        request_id=request_id,
                        started=started,
                        target_host=target_host,
                        status_code=495,
                        reason="Client TLS Handshake Failed",
                    )
                    return
            else:
                handle_connect_tunnel(
                    client_socket=self.connection,
                    target=target,
                    timeout_s=30.0,
                )
            self._log_connect_outcome(
                request_id=request_id,
                started=started,
                target_host=target_host,
                status_code=200,
                reason="Connection Established",
            )
            return
        except ValueError as exc:
            if request_id is None:
                server = self.server
                if not isinstance(server, ProxyHTTPServer):
                    return
                request_id = server.runtime_context.exchange_recorder.record_request(
                    method=self.command,
                    path=self.path,
                    client_ip=self.client_address[0],
                    headers={name: value for name, value in self.headers.items()},
                    body=b"",
                    target_host=target_host,
                    target_port=target_port,
                )
            response_body = f"Invalid CONNECT target: {exc}\n".encode("utf-8")
            self._respond_connect_error_and_log(
                request_id=request_id,
                started=started,
                target_host=target_host,
                status=400,
                reason="Bad CONNECT target",
                body=response_body,
            )
            return
        except ConnectUpstreamTimeoutError:
            response_body = b"CONNECT upstream timed out.\n"
            self._respond_connect_error_and_log(
                request_id=request_id,
                started=started,
                target_host=target_host,
                status=504,
                reason="Gateway Timeout",
                body=response_body,
            )
            return
        except ConnectUpstreamConnectionError:
            response_body = b"CONNECT upstream connection failed.\n"
            self._respond_connect_error_and_log(
                request_id=request_id,
                started=started,
                target_host=target_host,
                status=502,
                reason="Bad Gateway",
                body=response_body,
            )
            return
        finally:
            server = self.server
            if isinstance(server, ProxyHTTPServer):
                server.unregister_tunnel_socket(self.connection)

    def log_message(self, fmt: str, *args: object) -> None:
        # Route default request logs through the project logger.
        SERVER_LOGGER.debug(fmt, *args)


def create_server(
    host: str,
    port: int,
    *,
    runtime_context: ProxyRuntimeContext,
    forwarder: Forwarder | None = None,
    mitm_interceptor: MitmTLSInterceptor | None = None,
    auto_enable_mitm: bool = True,
    ca_root: str | Path | None = None,
) -> ProxyHTTPServer:
    resolved_forwarder = forwarder or UpstreamForwarder()
    resolved_mitm_interceptor = mitm_interceptor
    if resolved_mitm_interceptor is None and auto_enable_mitm:
        ca = default_ca() if ca_root is None else certificate_authority_for_root(ca_root)
        try:
            created_new_ca = ca.ensure_ca_material()
            if created_new_ca:
                SERVER_LOGGER.info(
                    "Generated local MITM CA materials cert=%s key=%s",
                    ca.ca_cert_path,
                    ca.ca_key_path,
                )
            resolved_mitm_interceptor = MitmTLSInterceptor(certificate_authority=ca, runtime_context=runtime_context)
        except MitmCertificateError as exc:
            SERVER_LOGGER.warning("MITM disabled: failed to initialize local CA: %s", exc)

    return ProxyHTTPServer(
        (host, port),
        RequestLoggingHandler,
        forwarder=resolved_forwarder,
        runtime_context=runtime_context,
        mitm_interceptor=resolved_mitm_interceptor,
    )


def _resolve_forward_request_target(forward_request: ForwardRequest) -> tuple[str | None, int | None]:
    try:
        target_url = resolve_target_url(forward_request)
    except ValueError:
        return None, None

    parsed = urlsplit(target_url)
    host = parsed.hostname
    if host is None:
        return None, None

    if parsed.port is not None:
        return host, parsed.port
    if parsed.scheme == "https":
        return host, 443
    return host, 80
