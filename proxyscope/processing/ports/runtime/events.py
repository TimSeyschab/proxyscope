from typing import Protocol, runtime_checkable


@runtime_checkable
class RuntimeEventSink(Protocol):
    def on_site_visit(self, host: str) -> None: ...
