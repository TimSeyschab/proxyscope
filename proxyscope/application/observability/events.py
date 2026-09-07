from typing import Protocol

from proxyscope.application.events import EventBus, RequestObserved, RuntimeEvent


class RuntimeObserver(Protocol):
    def on_site_visit(self, host: str) -> None: ...


class RuntimeEventDispatcher:
    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._observer: RuntimeObserver | None = None
        self._event_bus = event_bus or EventBus()
        self._event_bus.subscribe(lambda event: self._on_request_observed(event))

    def set_observer(self, observer: RuntimeObserver | None) -> None:
        self._observer = observer

    def on_site_visit(self, host: str) -> None:
        """Deprecated compatibility hook; recorder events drive observers."""
        return

    def _notify_site_visit(self, host: str) -> None:
        observer = self._observer
        if observer is None:
            return
        observer.on_site_visit(host)

    def _on_request_observed(self, event: RuntimeEvent) -> None:
        if isinstance(event, RequestObserved) and event.target_host is not None:
            self._notify_site_visit(event.target_host)
