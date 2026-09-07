import logging
from typing import Final

from proxyscope.application.events import (
    EventBus,
    ExchangeCompleted,
    RequestBodyCaptured,
    RequestObserved,
    ResponseBodyCaptured,
    ResponseObserved,
)
from proxyscope.application.journal import RequestJournal
from proxyscope.application.processing.models import ExchangeResponse
from proxyscope.application.runtime_settings import RuntimeSettingsState

REQUEST_LOGGER: Final = logging.getLogger("pscope.request")
RESPONSE_LOGGER: Final = logging.getLogger("pscope.response")


class RequestResponseRecorder:
    def __init__(
        self,
        *,
        settings: RuntimeSettingsState,
        request_journal: RequestJournal,
        event_bus: EventBus | None = None,
    ) -> None:
        self._settings = settings
        self._request_journal = request_journal
        self._event_bus = event_bus

    def record_request(
        self,
        *,
        method: str,
        path: str,
        client_ip: str,
        headers: dict[str, str],
        body: bytes = b"",
        target_host: str | None = None,
        target_port: int | None = None,
        protocol: str = "http",
    ) -> int | None:
        if not self._settings.should_log_for_host(target_host):
            return None

        REQUEST_LOGGER.info(
            "Incoming request method=%s path=%s client=%s target=%s",
            method,
            path,
            client_ip,
            _target_display(target_host, target_port),
        )

        request_id = self._request_journal.start_request(
            method=method,
            path=path,
            start_line=f"{method} {path}",
            headers=headers,
            body=body,
            client_ip=client_ip,
            target_host=target_host,
            target_port=target_port,
            protocol=protocol,
        )
        self._publish_request(
            request_id=request_id,
            method=method,
            path=path,
            target_host=target_host,
            target_port=target_port,
            protocol=protocol,
            body=body,
        )
        return request_id

    def record_response(
        self,
        response: ExchangeResponse,
        *,
        request_id: int | None,
        duration_ms: float,
        client_ip: str,
        target_host: str | None = None,
    ) -> None:
        if not self._settings.should_log_for_host(target_host):
            return

        body_size = response.body_size if response.body_size is not None else len(response.body)

        RESPONSE_LOGGER.info(
            "Outgoing response status=%s reason=%s client=%s body_bytes=%d duration_ms=%.2f",
            response.status_code,
            response.reason,
            client_ip,
            body_size,
            duration_ms,
        )

        if request_id is None:
            return

        self._request_journal.complete_request(
            request_id,
            status_code=response.status_code,
            reason=response.reason,
            start_line=f"HTTP/1.1 {response.status_code} {response.reason}",
            headers=response.headers,
            body=response.body,
            duration_ms=duration_ms,
            body_size=body_size,
        )
        self._publish_response(
            request_id=request_id,
            status_code=response.status_code,
            reason=response.reason,
            body_size=body_size,
            duration_ms=duration_ms,
            body=response.body,
        )

    def record_mitm_request(
        self,
        *,
        client_ip: str,
        target_host: str,
        target_port: int,
        start_line: str,
        headers: dict[str, str],
        body: bytes,
    ) -> int | None:
        if not self._settings.should_log_for_host(target_host):
            return None

        REQUEST_LOGGER.info(
            "MITM HTTP request client=%s target=%s:%d start_line=%s",
            client_ip,
            target_host,
            target_port,
            start_line,
        )

        method, path = _parse_request_start_line(start_line)
        request_id = self._request_journal.start_request(
            method=method,
            path=path,
            start_line=start_line,
            headers=headers,
            body=body,
            client_ip=client_ip,
            target_host=target_host,
            target_port=target_port,
            protocol="https-mitm",
        )
        self._publish_request(
            request_id=request_id,
            method=method,
            path=path,
            target_host=target_host,
            target_port=target_port,
            protocol="https-mitm",
            body=body,
        )
        return request_id

    def record_mitm_response(
        self,
        *,
        client_ip: str,
        target_host: str,
        target_port: int,
        start_line: str,
        headers: dict[str, str],
        body: bytes,
        request_id: int | None,
    ) -> None:
        if not self._settings.should_log_for_host(target_host):
            return

        RESPONSE_LOGGER.info(
            "MITM HTTP response client=%s target=%s:%d start_line=%s",
            client_ip,
            target_host,
            target_port,
            start_line,
        )

        if request_id is None:
            return

        status_code, reason = _parse_response_start_line(start_line)
        self._request_journal.complete_request(
            request_id,
            status_code=status_code,
            reason=reason,
            start_line=start_line,
            headers=headers,
            body=body,
            duration_ms=0.0,
            body_size=len(body),
        )
        self._publish_response(
            request_id=request_id,
            status_code=status_code,
            reason=reason,
            body_size=len(body),
            duration_ms=0.0,
            body=body,
        )

    def _publish_request(
        self,
        *,
        request_id: int | None,
        method: str,
        path: str,
        target_host: str | None,
        target_port: int | None,
        protocol: str,
        body: bytes,
    ) -> None:
        if self._event_bus is None:
            return
        self._event_bus.publish(
            RequestObserved(
                request_id=request_id,
                method=method,
                path=path,
                target_host=target_host,
                target_port=target_port,
                protocol=protocol,
            )
        )
        if body:
            self._event_bus.publish(RequestBodyCaptured(request_id=request_id, body_size=len(body), body=body))

    def _publish_response(
        self,
        *,
        request_id: int,
        status_code: int,
        reason: str,
        body_size: int,
        duration_ms: float,
        body: bytes | None = None,
    ) -> None:
        if self._event_bus is None:
            return
        self._event_bus.publish(
            ResponseObserved(
                request_id=request_id,
                status_code=status_code,
                reason=reason,
                body_size=body_size,
            )
        )
        if body_size:
            self._event_bus.publish(ResponseBodyCaptured(request_id=request_id, body_size=body_size, body=body))
        self._event_bus.publish(ExchangeCompleted(request_id=request_id, duration_ms=duration_ms))


def _parse_request_start_line(start_line: str) -> tuple[str, str]:
    parts = start_line.split(" ", 2)
    if len(parts) >= 2:
        return parts[0], parts[1]
    return "UNKNOWN", start_line


def _parse_response_start_line(start_line: str) -> tuple[int, str]:
    parts = start_line.split(" ", 2)
    if len(parts) >= 2:
        try:
            status_code = int(parts[1])
        except ValueError:
            status_code = 0
        reason = parts[2] if len(parts) >= 3 else ""
        return status_code, reason
    return 0, ""


def _target_display(host: str | None, port: int | None) -> str:
    if host is None:
        return "-"
    if port is None:
        return host
    return f"{host}:{port}"
