from __future__ import annotations

from datetime import datetime

from proxyscope.application.events import RuntimeEvent
from proxyscope.contracts.event_store import EventStore, StoredEvent


class NoopEventStore:
    def append(self, event: RuntimeEvent) -> None:
        return None

    def list_events(
        self,
        *,
        request_id: int | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
    ) -> tuple[StoredEvent, ...]:
        return ()

    def close(self) -> None:
        return None


class EventStoreWriter:
    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store

    def __call__(self, event: RuntimeEvent) -> None:
        self._event_store.append(event)


__all__ = ["EventStore", "EventStoreWriter", "NoopEventStore", "StoredEvent"]
