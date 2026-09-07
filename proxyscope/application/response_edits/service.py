import logging
from dataclasses import dataclass, field, replace
from queue import Empty, Queue
from threading import Event, Lock

from proxyscope.application.artifacts import ArtifactStatus, ArtifactStore, ResponseEditArtifact, create_body_reference
from proxyscope.application.events import ArtifactRecorded, EventBus, ResponseEditApplied, ResponseEditRequested
from proxyscope.application.processing.headers import headers_for_body
from proxyscope.application.processing.models import ExchangeResponse

LOGGER = logging.getLogger("pscope.response_modifier")


@dataclass
class PendingResponseEdit:
    request_url: str
    method: str
    response: ExchangeResponse
    _done: Event
    source_request_id: int | None = None
    artifact: ResponseEditArtifact | None = None
    _result: ExchangeResponse | None = None
    _lock: Lock = field(default_factory=Lock)

    def apply(self, *, headers: dict[str, str], body: bytes) -> bool:
        updated_headers = headers_for_body(headers, body)
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


@dataclass(frozen=True)
class ResponseEditorResult:
    success: bool
    message: str
    headers: dict[str, str] | None = None
    body: bytes | None = None


class ResponseModifierService:
    def __init__(
        self,
        *,
        interactive_enabled: bool = False,
        edit_timeout_s: float = 60.0,
        event_bus: EventBus | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        if edit_timeout_s <= 0:
            raise ValueError("edit_timeout_s must be greater than zero.")
        self._interactive_enabled = interactive_enabled
        self._edit_timeout_s = edit_timeout_s
        self._queue: Queue[PendingResponseEdit] = Queue()
        self._pending: dict[int, PendingResponseEdit] = {}
        self._lock = Lock()
        self._event_bus = event_bus
        self._artifact_store = artifact_store

    def set_interactive_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._interactive_enabled = enabled

    def maybe_modify_response(
        self,
        *,
        request_url: str,
        method: str,
        response: ExchangeResponse,
        source_request_id: int | None = None,
    ) -> ExchangeResponse:
        with self._lock:
            interactive_enabled = self._interactive_enabled
        if not interactive_enabled:
            LOGGER.warning("Response modification requested for %s but interactive editor is disabled.", request_url)
            return response

        artifact = ResponseEditArtifact(
            source_request_id=source_request_id,
            method=method,
            request_url=request_url,
            headers=tuple(response.headers.items()),
            body=(
                create_body_reference(response.body)
                if self._artifact_store is None
                else self._artifact_store.body_reference(response.body)
            ),
            status=ArtifactStatus.RUNNING,
        )
        if self._artifact_store is not None:
            self._artifact_store.add(artifact)
        task = PendingResponseEdit(
            request_url=request_url,
            method=method,
            response=response,
            _done=Event(),
            source_request_id=source_request_id,
            artifact=artifact,
        )
        with self._lock:
            self._pending[id(task)] = task
        if self._event_bus is not None:
            self._event_bus.publish(
                ResponseEditRequested(
                    request_id=source_request_id,
                    request_url=request_url,
                    method=method,
                    artifact_id=artifact.edit_id,
                )
            )
            self._event_bus.publish(
                ArtifactRecorded(
                    request_id=source_request_id,
                    artifact_id=artifact.edit_id,
                    artifact_type="response_edit",
                    status=artifact.status,
                )
            )
        self._queue.put(task)
        result = task.wait(timeout_s=self._edit_timeout_s)
        with self._lock:
            self._pending.pop(id(task), None)
        if not task.is_done:
            task.keep_original()
            LOGGER.warning("Response edit timed out for %s; kept original response.", request_url)
        if self._event_bus is not None:
            self._event_bus.publish(
                ResponseEditApplied(
                    request_id=source_request_id,
                    request_url=request_url,
                    applied=result != response,
                    artifact_id=artifact.edit_id,
                )
            )
        return result

    def record_artifact_result(
        self,
        pending: PendingResponseEdit,
        *,
        status: ArtifactStatus,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        error: str | None = None,
    ) -> None:
        artifact = pending.artifact
        if artifact is None or self._artifact_store is None:
            return
        updated = replace(
            artifact,
            headers=tuple((headers or dict(artifact.headers)).items()),
            body=artifact.body if body is None else self._artifact_store.body_reference(body),
            status=status,
            error=error,
        )
        self._artifact_store.replace(updated)
        if self._event_bus is not None:
            self._event_bus.publish(
                ArtifactRecorded(
                    request_id=pending.source_request_id,
                    artifact_id=updated.edit_id,
                    artifact_type="response_edit",
                    status=updated.status,
                    error=updated.error,
                )
            )

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
