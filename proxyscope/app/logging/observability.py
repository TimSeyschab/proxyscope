from threading import Lock
from typing import Protocol


class RuntimeObserver(Protocol):
    def on_site_visit(self, host: str) -> None: ...


class RuntimeEventDispatcher:
    def __init__(self) -> None:
        self._lock = Lock()
        self._observer: RuntimeObserver | None = None

    def set_observer(self, observer: RuntimeObserver | None) -> None:
        with self._lock:
            self._observer = observer

    def on_site_visit(self, host: str) -> None:
        with self._lock:
            observer = self._observer
        if observer is None:
            return
        observer.on_site_visit(host)
