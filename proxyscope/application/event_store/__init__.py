"""Event-store ports and default implementations."""

from .store import EventStore, EventStoreWriter, NoopEventStore, StoredEvent

__all__ = ["EventStore", "EventStoreWriter", "NoopEventStore", "StoredEvent"]
