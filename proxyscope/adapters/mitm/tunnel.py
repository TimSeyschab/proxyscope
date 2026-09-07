import socket
import ssl
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from proxyscope.adapters.mitm.certificates import MitmCertificateAuthority
from proxyscope.adapters.proxy.connect_tunnel import (
    ConnectTarget,
    ConnectUpstreamConnectionError,
    ConnectUpstreamTimeoutError,
)
from proxyscope.adapters.proxy.http1_request_rewriter import HTTP1RequestHeaderRewriter
from proxyscope.adapters.proxy.http1_response_modifier_rewriter import HTTP1ResponseModifierRewriter
from proxyscope.adapters.proxy.http1_sniffer import HTTP1MessageSniffer
from proxyscope.application.processing.models import ExchangeRequest, ExchangeResponse, PreparedExchange
from proxyscope.application.proxy.runtime import ProxyRuntimeContext


@dataclass(frozen=True)
class MitmTLSInterceptor:
    certificate_authority: MitmCertificateAuthority
    runtime_context: ProxyRuntimeContext

    def intercept(self, *, client_socket: socket.socket, target: ConnectTarget, timeout_s: float = 30.0) -> bool:
        """
        Perform MITM TLS interception for a CONNECT tunnel.

        Flow:
        1) connect proxy->upstream and establish TLS (as a client)
        2) send 200 Connection Established to the browser
        3) establish TLS browser->proxy (as a server with forged host cert)
        4) relay decrypted bytes between both TLS sessions

        Returns:
        - True if tunnel handshake succeeded and relay ran.
        - False if client rejected proxy certificate during TLS handshake.
        """
        try:
            upstream_tcp = socket.create_connection((target.host, target.port), timeout=timeout_s)
        except socket.timeout as exc:
            raise ConnectUpstreamTimeoutError(
                f"Timed out connecting to upstream target {target.host}:{target.port}."
            ) from exc
        except OSError as exc:
            raise ConnectUpstreamConnectionError(
                f"Failed to connect to upstream target {target.host}:{target.port}: {exc}"
            ) from exc

        with upstream_tcp:
            upstream_ctx = ssl.create_default_context()
            # Prefer HTTP/1.1 in MITM mode to keep decrypted stream logging practical.
            upstream_ctx.set_alpn_protocols(["http/1.1"])
            try:
                upstream_tls = upstream_ctx.wrap_socket(upstream_tcp, server_hostname=target.host)
            except ssl.SSLError as exc:
                raise ConnectUpstreamConnectionError(
                    f"Failed TLS handshake with upstream target {target.host}:{target.port}: {exc}"
                ) from exc

            with upstream_tls:
                # Tell the client to start TLS over this proxy connection.
                client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

                cert_path, key_path = self.certificate_authority.issue_host_certificate(target.host)
                client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                client_ctx.set_alpn_protocols(["http/1.1"])
                client_ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
                try:
                    client_tls = client_ctx.wrap_socket(client_socket, server_side=True)
                except ssl.SSLError:
                    # Client rejected the forged MITM certificate (usually trust issue).
                    # At this point HTTP 200 was already sent, so we just stop tunneling.
                    return False

                with client_tls:
                    try:
                        client_ip = client_socket.getpeername()[0]
                    except OSError:
                        client_ip = "unknown"

                    pending_exchanges: deque[PreparedExchange] = deque()
                    pending_lock = threading.Lock()

                    def on_request(start_line: str, headers: dict[str, str], body: bytes) -> None:
                        method, path = _parse_request_start_line(start_line)
                        request_url = _build_https_request_url(host=target.host, port=target.port, path=path)
                        exchange = self.runtime_context.exchange_pipeline.prepare_request(
                            ExchangeRequest(
                                method=method,
                                url=request_url,
                                path=path,
                                headers=headers,
                                body=body,
                                client_ip=client_ip,
                                target_host=target.host,
                                target_port=target.port,
                                protocol="https-mitm",
                            )
                        )
                        with pending_lock:
                            pending_exchanges.append(exchange)

                    def process_response(response: ExchangeResponse) -> ExchangeResponse:
                        with pending_lock:
                            exchange = pending_exchanges.popleft() if pending_exchanges else None
                        if exchange is None:
                            return response
                        return self.runtime_context.exchange_pipeline.process_response(exchange, response)

                    def acquire_request_method() -> str | None:
                        with pending_lock:
                            if not pending_exchanges:
                                return None
                            return pending_exchanges[0].request.method

                    request_sniffer = HTTP1MessageSniffer(on_request)
                    response_sniffer = HTTP1MessageSniffer(lambda _start_line, _headers, _body: None)
                    response_rewriter = HTTP1ResponseModifierRewriter(
                        process_response=process_response,
                        acquire_request_method=acquire_request_method,
                    )
                    _relay_tls_bidirectional(
                        client_tls,
                        upstream_tls,
                        timeout_s=timeout_s,
                        request_sniffer=request_sniffer,
                        response_sniffer=response_sniffer,
                        response_rewriter=response_rewriter,
                        rewrite_request_headers=self.runtime_context.exchange_pipeline.rewrite_request_headers,
                    )
                return True


def _relay_tls_bidirectional(
    client_tls: ssl.SSLSocket,
    upstream_tls: ssl.SSLSocket,
    *,
    timeout_s: float,
    request_sniffer: HTTP1MessageSniffer,
    response_sniffer: HTTP1MessageSniffer,
    response_rewriter: HTTP1ResponseModifierRewriter,
    rewrite_request_headers: Callable[[dict[str, str]], dict[str, str]] | None,
) -> None:
    """
    Relay bytes in both directions using two threads.
    """
    stop_event = threading.Event()
    relay_error: list[Exception] = []
    relay_lock = threading.Lock()
    idle_deadline = time.monotonic() + timeout_s
    idle_lock = threading.Lock()

    def pump(
        source: ssl.SSLSocket,
        destination: ssl.SSLSocket,
        sniffer: HTTP1MessageSniffer,
        *,
        rewriter: HTTP1RequestHeaderRewriter | None = None,
        response_modifier_rewriter: HTTP1ResponseModifierRewriter | None = None,
    ) -> None:
        nonlocal idle_deadline
        source.settimeout(timeout_s)
        destination.settimeout(timeout_s)
        try:
            while not stop_event.is_set():
                try:
                    data = source.recv(65536)
                except socket.timeout:
                    # Idle socket timeouts are expected for keep-alive HTTPS connections.
                    # Close gracefully only if both directions stayed idle beyond timeout_s.
                    with idle_lock:
                        if time.monotonic() >= idle_deadline:
                            return
                    continue

                if not data:
                    if rewriter is not None:
                        flushed = rewriter.flush()
                        if flushed:
                            sniffer.feed(flushed)
                            destination.sendall(flushed)
                    if response_modifier_rewriter is not None:
                        flushed = response_modifier_rewriter.flush()
                        if flushed:
                            sniffer.feed(flushed)
                            destination.sendall(flushed)
                    return
                with idle_lock:
                    idle_deadline = time.monotonic() + timeout_s
                payload = data
                if rewriter is not None:
                    payload = rewriter.feed(data)
                if response_modifier_rewriter is not None:
                    payload = response_modifier_rewriter.feed(payload)
                if not payload:
                    continue
                sniffer.feed(payload)
                destination.sendall(payload)
        except Exception as exc:  # noqa: BLE001
            with relay_lock:
                relay_error.append(exc)
        finally:
            stop_event.set()
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    request_rewriter = HTTP1RequestHeaderRewriter(rewrite_request_headers) if rewrite_request_headers else None
    t1 = threading.Thread(
        target=pump,
        args=(client_tls, upstream_tls, request_sniffer),
        kwargs={"rewriter": request_rewriter},
        daemon=True,
    )
    t2 = threading.Thread(
        target=pump,
        args=(upstream_tls, client_tls, response_sniffer),
        kwargs={"response_modifier_rewriter": response_rewriter},
        daemon=True,
    )
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    if relay_error:
        first_error = relay_error[0]
        if isinstance(first_error, ConnectUpstreamTimeoutError):
            raise first_error
        # Ignore clean EOF-like SSL errors; raise only obvious transport issues.
        if isinstance(first_error, (ssl.SSLError, OSError)):
            return
        raise first_error


def _parse_request_start_line(start_line: str) -> tuple[str, str]:
    parts = start_line.split(" ", 2)
    if len(parts) >= 2:
        return parts[0], parts[1]
    return "GET", "/"


def _build_https_request_url(*, host: str, port: int, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    normalized_path = path if path.startswith("/") else f"/{path}"
    if port == 443:
        return f"https://{host}{normalized_path}"
    return f"https://{host}:{port}{normalized_path}"
