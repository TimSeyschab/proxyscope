from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from proxyscope.contracts.events import RuntimeEvent

EventHandler = Callable[[RuntimeEvent], object]


class ComponentEventBus(Protocol):
    def publish(self, event: RuntimeEvent) -> None: ...

    def subscribe(self, handler: EventHandler) -> None: ...

    def unsubscribe(self, handler: EventHandler) -> None: ...


@dataclass(frozen=True)
class CapturedResponse:
    status_code: int
    reason: str
    headers: tuple[tuple[str, str], ...]
    body: bytes | None
    body_size: int | None
    start_line: str = ""


@dataclass(frozen=True)
class CapturedExchange:
    request_id: int
    method: str
    url: str | None
    response: CapturedResponse | None
    path: str = ""
    start_line: str = ""
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes | None = None
    client_ip: str = ""
    target_host: str | None = None
    target_port: int | None = None
    protocol: str = "http"
    duration_ms: float | None = None


class ComponentJournal(Protocol):
    def get_entry(self, request_id: int) -> CapturedExchange | None: ...

    def list_entries(self) -> tuple[CapturedExchange, ...]: ...
