import logging
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Lock

from proxyscope.processing.models import ExchangeResponse

LOGGER = logging.getLogger("tproxy.response_modifier")


@dataclass
class PendingResponseEdit:
    request_url: str
    method: str
    response: ExchangeResponse
    _done: Event
    _result: ExchangeResponse | None = None

    def apply(self, *, headers: dict[str, str], body: bytes) -> None:
        updated_headers = dict(headers)
        _remove_header_case_insensitive(updated_headers, "Transfer-Encoding")
        updated_headers["Content-Length"] = str(len(body))
        self._result = ExchangeResponse(
            status_code=self.response.status_code,
            reason=self.response.reason,
            headers=updated_headers,
            body=body,
        )
        self._done.set()

    def keep_original(self) -> None:
        self._result = self.response
        self._done.set()

    def wait(self, *, timeout_s: float | None = None) -> ExchangeResponse:
        finished = self._done.wait(timeout=timeout_s)
        if not finished or self._result is None:
            return self.response
        return self._result


class ResponseModifierService:
    def __init__(self, *, interactive_enabled: bool = False) -> None:
        self._interactive_enabled = interactive_enabled
        self._queue: Queue[PendingResponseEdit] = Queue()
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
        self._queue.put(task)
        return task.wait()

    def poll_pending_edit(self) -> PendingResponseEdit | None:
        try:
            return self._queue.get_nowait()
        except Empty:
            return None


def _remove_header_case_insensitive(headers: dict[str, str], header_name: str) -> None:
    target = header_name.lower()
    for key in list(headers.keys()):
        if key.lower() == target:
            del headers[key]
