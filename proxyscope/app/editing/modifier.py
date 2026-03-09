from dataclasses import dataclass
import logging
from queue import Empty, Queue
from threading import Event, Lock

from proxyscope.app.config.runtime import should_modify_response_for_request
from proxyscope.proxy.forwarding import ForwardResponse

LOGGER = logging.getLogger("tproxy.response_modifier")


@dataclass
class PendingResponseEdit:
    request_url: str
    method: str
    response: ForwardResponse
    _done: Event
    _result: ForwardResponse | None = None

    def apply(self, *, headers: dict[str, str], body: bytes) -> None:
        updated_headers = dict(headers)
        _remove_header_case_insensitive(updated_headers, "Transfer-Encoding")
        updated_headers["Content-Length"] = str(len(body))
        self._result = ForwardResponse(
            status_code=self.response.status_code,
            reason=self.response.reason,
            headers=updated_headers,
            body=body,
        )
        self._done.set()

    def keep_original(self) -> None:
        self._result = self.response
        self._done.set()

    def wait(self, *, timeout_s: float | None = None) -> ForwardResponse:
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

    def maybe_modify_response(self, *, request_url: str, method: str, response: ForwardResponse) -> ForwardResponse:
        if not should_modify_response_for_request(method=method, url=request_url):
            return response

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


_response_modifier = ResponseModifierService()
_response_modifier_lock = Lock()


def set_response_modifier(service: ResponseModifierService) -> None:
    global _response_modifier
    with _response_modifier_lock:
        _response_modifier = service


def get_response_modifier() -> ResponseModifierService:
    with _response_modifier_lock:
        return _response_modifier


def _remove_header_case_insensitive(headers: dict[str, str], header_name: str) -> None:
    target = header_name.lower()
    for key in list(headers.keys()):
        if key.lower() == target:
            del headers[key]
