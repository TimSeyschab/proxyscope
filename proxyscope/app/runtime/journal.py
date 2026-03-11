from dataclasses import dataclass, replace
from threading import RLock
from time import time


@dataclass(frozen=True)
class LoggedRequestMessage:
    method: str
    path: str
    start_line: str
    headers: tuple[tuple[str, str], ...]
    body_preview: str
    body: bytes | None


@dataclass(frozen=True)
class LoggedResponseMessage:
    status_code: int
    reason: str
    start_line: str
    headers: tuple[tuple[str, str], ...]
    body_preview: str
    body_size: int | None


@dataclass(frozen=True)
class LoggedExchange:
    request_id: int
    started_at: float
    finished_at: float | None
    duration_ms: float | None
    client_ip: str
    target_host: str | None
    target_port: int | None
    protocol: str
    request: LoggedRequestMessage
    response: LoggedResponseMessage | None


class RequestJournal:
    """
    Central in-memory request/response log storage for the runtime UI.
    """

    def __init__(self, *, max_entries: int = 1000) -> None:
        self._lock = RLock()
        self._max_entries = max_entries
        self._next_id = 1
        self._entries: list[LoggedExchange] = []

    def start_request(
        self,
        *,
        method: str,
        path: str,
        start_line: str,
        headers: dict[str, str],
        body: bytes | None,
        client_ip: str,
        target_host: str | None,
        target_port: int | None,
        protocol: str,
    ) -> int:
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            exchange = LoggedExchange(
                request_id=request_id,
                started_at=time(),
                finished_at=None,
                duration_ms=None,
                client_ip=client_ip,
                target_host=target_host,
                target_port=target_port,
                protocol=protocol,
                request=LoggedRequestMessage(
                    method=method,
                    path=path,
                    start_line=start_line,
                    headers=tuple(headers.items()),
                    body_preview=_body_preview(body),
                    body=body,
                ),
                response=None,
            )
            self._entries.append(exchange)
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries :]
            return request_id

    def complete_request(
        self,
        request_id: int,
        *,
        status_code: int,
        reason: str,
        start_line: str,
        headers: dict[str, str],
        body: bytes | None,
        duration_ms: float,
        body_size: int | None = None,
    ) -> None:
        with self._lock:
            for index, entry in enumerate(self._entries):
                if entry.request_id != request_id:
                    continue
                updated = replace(
                    entry,
                    finished_at=time(),
                    duration_ms=duration_ms,
                    response=LoggedResponseMessage(
                        status_code=status_code,
                        reason=reason,
                        start_line=start_line,
                        headers=tuple(headers.items()),
                        body_preview=_body_preview(body, total_bytes=body_size),
                        body_size=body_size if body_size is not None else (len(body) if body is not None else None),
                    ),
                )
                self._entries[index] = updated
                return

    def list_entries(self) -> tuple[LoggedExchange, ...]:
        with self._lock:
            return tuple(self._entries)

    def get_entry(self, request_id: int) -> LoggedExchange | None:
        with self._lock:
            for entry in self._entries:
                if entry.request_id == request_id:
                    return entry
        return None

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def replace_entries(self, entries: list[LoggedExchange]) -> None:
        with self._lock:
            self._entries = list(entries)
            max_request_id = max((entry.request_id for entry in self._entries), default=0)
            self._next_id = max_request_id + 1


_request_journal = RequestJournal()
_request_journal_lock = RLock()


def set_request_journal(journal: RequestJournal) -> None:
    global _request_journal
    with _request_journal_lock:
        _request_journal = journal


def get_request_journal() -> RequestJournal:
    with _request_journal_lock:
        return _request_journal


def _body_preview(body: bytes | None, *, max_bytes: int = 4096, total_bytes: int | None = None) -> str:
    if body is None:
        return "<not captured>"
    if not body:
        return ""

    prefix = body[:max_bytes]
    text = prefix.decode("utf-8", errors="replace").replace("\x00", "\\x00")
    effective_total = len(body) if total_bytes is None else max(total_bytes, len(body))
    if effective_total <= len(prefix):
        return text
    remaining = effective_total - len(prefix)
    return f"{text}\n...[truncated {remaining} bytes]"
