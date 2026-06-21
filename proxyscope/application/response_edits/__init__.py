import logging
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Lock

from proxyscope.processing.models import ExchangeResponse

LOGGER = logging.getLogger("pscope.response_modifier")


@dataclass
class PendingResponseEdit:
    request_url: str
    method: str
    response: ExchangeResponse
    _done: Event
    _result: ExchangeResponse | None = None
    _lock: Lock = field(default_factory=Lock)

    def apply(self, *, headers: dict[str, str], body: bytes) -> bool:
        updated_headers = dict(headers)
        _remove_header_case_insensitive(updated_headers, "Transfer-Encoding")
        updated_headers["Content-Length"] = str(len(body))
        with self._lock:
            if self._done.is_set():
                return False
            self._result = ExchangeResponse(
                status_code=self.response.status_code,
                reason=self.response.reason,
                headers=updated_headers,
                body=body,
            )
            self._done.set()
        return True

    def keep_original(self) -> bool:
        with self._lock:
            if self._done.is_set():
                return False
            self._result = self.response
            self._done.set()
        return True

    def wait(self, *, timeout_s: float | None = None) -> ExchangeResponse:
        finished = self._done.wait(timeout=timeout_s)
        if not finished or self._result is None:
            return self.response
        return self._result

    @property
    def is_done(self) -> bool:
        return self._done.is_set()


class ResponseModifierService:
    def __init__(self, *, interactive_enabled: bool = False, edit_timeout_s: float = 60.0) -> None:
        if edit_timeout_s <= 0:
            raise ValueError("edit_timeout_s must be greater than zero.")
        self._interactive_enabled = interactive_enabled
        self._edit_timeout_s = edit_timeout_s
        self._queue: Queue[PendingResponseEdit] = Queue()
        self._pending: dict[int, PendingResponseEdit] = {}
        self._lock = Lock()

    def set_interactive_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._interactive_enabled = enabled

    def maybe_modify_response(self, *, request_url: str, method: str, response: ExchangeResponse) -> ExchangeResponse:
        with self._lock:
            interactive_enabled = self._interactive_enabled
        if not interactive_enabled:
            LOGGER.warning("Response modification requested for %s but interactive editor is disabled.", request_url)
            return response

        task = PendingResponseEdit(
            request_url=request_url,
            method=method,
            response=response,
            _done=Event(),
        )
        with self._lock:
            self._pending[id(task)] = task
        self._queue.put(task)
        result = task.wait(timeout_s=self._edit_timeout_s)
        with self._lock:
            self._pending.pop(id(task), None)
        if not task.is_done:
            task.keep_original()
            LOGGER.warning("Response edit timed out for %s; kept original response.", request_url)
        return result

    def poll_pending_edit(self) -> PendingResponseEdit | None:
        while True:
            try:
                pending = self._queue.get_nowait()
            except Empty:
                return None
            if not pending.is_done:
                return pending

    def cancel_pending_edits(self) -> int:
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        cancelled = sum(task.keep_original() for task in pending)
        return cancelled


def _remove_header_case_insensitive(headers: dict[str, str], header_name: str) -> None:
    target = header_name.lower()
    for key in list(headers.keys()):
        if key.lower() == target:
            del headers[key]
