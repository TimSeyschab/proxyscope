from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from proxyscope.contracts.events import RuntimeEvent


@dataclass(frozen=True)
class StoredEvent:
    event_id: str
    event_type: str
    occurred_at: datetime
    request_id: int | None
    component_id: str | None
    target_host: str | None
    method: str | None
    status_code: int | None
    payload_version: int
    payload: dict[str, object]


@runtime_checkable
class EventStore(Protocol):
    def append(self, event: RuntimeEvent) -> None: ...

    def list_events(
        self,
        *,
        request_id: int | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
    ) -> tuple[StoredEvent, ...]: ...

    def close(self) -> None: ...
