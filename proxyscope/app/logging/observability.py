from threading import Lock
from typing import Protocol


class RuntimeObserver(Protocol):
    def on_site_visit(self, host: str) -> None: ...


_observer_lock = Lock()
_observer: RuntimeObserver | None = None


def set_runtime_observer(observer: RuntimeObserver | None) -> None:
    global _observer
    with _observer_lock:
        _observer = observer


def emit_site_visit(host: str) -> None:
    with _observer_lock:
        observer = _observer
    if observer is None:
        return
    observer.on_site_visit(host)
