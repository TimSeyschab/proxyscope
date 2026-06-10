import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from proxyscope.app.config.runtime import get_static_response_template_for_request, should_modify_response_for_request
from proxyscope.app.editing.modifier import get_response_modifier
from proxyscope.app.logging.observability import emit_site_visit
from proxyscope.app.logging.request_response import REQUEST_LOGGER, log_incoming_request, log_outgoing_response
from proxyscope.mitm.certificates import MitmCertificateError, certificate_authority_for_root, default_ca
from proxyscope.mitm.tunnel import MitmTLSInterceptor
from proxyscope.proxy.connect_tunnel import (
    ConnectUpstreamConnectionError,
    ConnectUpstreamTimeoutError,
    handle_connect_tunnel,
    parse_connect_target,
)
from proxyscope.proxy.forwarding import (
    BODY_PREVIEW_BYTES,
    STREAM_CHUNK_SIZE,
    ForwardRequest,
    ForwardResponse,
    UpstreamForwarder,
    capture_body_preview,
    prepare_forward_headers,
    prepare_forward_request,
    resolve_target_url,
)
from proxyscope.proxy.http_bridge import map_incoming_request, write_forward_response
from proxyscope.proxy.tunnel_registry import TunnelConnectionRegistry
from proxyscope.proxy.types import Forwarder

SERVER_LOGGER: Final = logging.getLogger("tproxy.server")


class ProxyHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        forwarder: Forwarder,
        mitm_interceptor: MitmTLSInterceptor | None = None,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.forwarder = forwarder
        self.mitm_interceptor = mitm_interceptor
        self._tunnel_registry = TunnelConnectionRegistry()

    def register_tunnel_socket(self, sock: object) -> None:
        self._tunnel_registry.register(sock)

    def unregister_tunnel_socket(self, sock: object) -> None:
        self._tunnel_registry.unregister(sock)

    def close_all_active_tunnels(self) -> int:
        return self._tunnel_registry.close_all()


class RequestLoggingHandler(BaseHTTPRequestHandler):
    server_version = "tproxy/0.1"

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
        log_outgoing_response(
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
        forwarder: UpstreamForwarder,
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
                    upstream_response.raw.stream(STREAM_CHUNK_SIZE, decode_content=False),
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
        effective_headers = prepare_forward_headers(forward_request.headers)
        forward_request = ForwardRequest(
            method=forward_request.method,
            path=forward_request.path,
            headers=effective_headers,
            body=forward_request.body,
        )
        target_host, target_port = _resolve_forward_request_target(forward_request)
        request_id = log_incoming_request(
            method=self.command,
            path=forward_request.path,
            client_ip=self.client_address[0],
            headers=effective_headers,
            body=forward_request.body,
            target_host=target_host,
            target_port=target_port,
        )
        try:
            if target_host:
                emit_site_visit(target_host)
        except ValueError:
            pass
        try:
            target_url = resolve_target_url(forward_request)
        except ValueError as exc:
            error_body = f"{exc}\n".encode("utf-8")
            self.send_response(400, "Bad Request")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(error_body)))
            self.end_headers()
            if send_body:
                self.wfile.write(error_body)
            duration_ms = (time.perf_counter() - started) * 1000
            log_outgoing_response(
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

        static_template = get_static_response_template_for_request(method=self.command, url=target_url)
        should_modify = should_modify_response_for_request(method=self.command, url=target_url)
        if static_template is not None:
            forward_response = ForwardResponse(
                status_code=static_template.status_code,
                reason=static_template.reason,
                headers=dict(static_template.headers),
                body=static_template.body,
                body_size=len(static_template.body),
            )
        elif isinstance(server.forwarder, UpstreamForwarder) and not should_modify:
            forward_response = self._forward_upstream_streaming(
                server.forwarder,
                forward_request,
                send_body=send_body,
            )
            duration_ms = (time.perf_counter() - started) * 1000
            log_outgoing_response(
                forward_response,
                request_id=request_id,
                duration_ms=duration_ms,
                client_ip=self.client_address[0],
                target_host=target_host,
            )
            return
        else:
            forward_response = server.forwarder.forward(forward_request)
        if static_template is None:
            modifier = get_response_modifier()
            forward_response = modifier.maybe_modify_response(
                request_url=target_url,
                method=self.command,
                response=forward_response,
            )
        write_forward_response(self, forward_response, send_body=send_body)

        duration_ms = (time.perf_counter() - started) * 1000
        log_outgoing_response(
            forward_response,
            request_id=request_id,
            duration_ms=duration_ms,
            client_ip=self.client_address[0],
            target_host=target_host,
        )

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
            request_id = log_incoming_request(
                method=self.command,
                path=self.path,
                client_ip=self.client_address[0],
                headers={name: value for name, value in self.headers.items()},
                body=b"",
                target_host=target_host,
                target_port=target_port,
            )
            emit_site_visit(target.host)
            server = self.server
            if not isinstance(server, ProxyHTTPServer):
                self.send_error(500, "Server misconfiguration")
                return
            server.register_tunnel_socket(self.connection)

            if server.mitm_interceptor is not None:
                tunnel_established = server.mitm_interceptor.intercept(
                    client_socket=self.connection,
                    target=target,
                    timeout_s=30.0,
                )
                if not tunnel_established:
                    REQUEST_LOGGER.warning(
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
                request_id = log_incoming_request(
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
    forwarder: Forwarder | None = None,
    mitm_interceptor: MitmTLSInterceptor | None = None,
    auto_enable_mitm: bool = True,
    ca_root: str | Path | None = None,
) -> ThreadingHTTPServer:
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
            resolved_mitm_interceptor = MitmTLSInterceptor(certificate_authority=ca)
        except MitmCertificateError as exc:
            SERVER_LOGGER.warning("MITM disabled: failed to initialize local CA: %s", exc)

    return ProxyHTTPServer(
        (host, port),
        RequestLoggingHandler,
        forwarder=resolved_forwarder,
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
