from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from proxyscope.contracts.commands import CommandDefinition
from proxyscope.contracts.event_store import EventStore
from proxyscope.contracts.ports import ComponentEventBus, ComponentJournal
from proxyscope.contracts.shortcuts import ShortcutDefinition

CORE_COMPONENT_ID = "core"


class ComponentController(Protocol):
    def list_statuses(self) -> tuple[tuple[str, str], ...]: ...
    def describe(self, component_id: str) -> str: ...
    def activate(self, component_id: str) -> None: ...
    def deactivate(self, component_id: str) -> None: ...


@dataclass(frozen=True)
class ComponentContribution:
    component_id: str
    display_name: str
    commands: tuple[CommandDefinition, ...] = ()
    shortcuts: tuple[ShortcutDefinition, ...] = ()
    event_handlers: tuple[object, ...] = ()
    ui_panels: tuple[object, ...] = ()
    request_middlewares: tuple[object, ...] = ()
    response_middlewares: tuple[object, ...] = ()
    on_activate: Callable[[], None] | None = None
    on_deactivate: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        normalized = normalize_component_id(self.component_id)
        if normalized != self.component_id:
            raise ValueError("component_id must already be normalized.")
        if not self.display_name.strip():
            raise ValueError("display_name must not be empty.")


@dataclass(frozen=True)
class ComponentContext:
    commands: tuple[CommandDefinition, ...] = ()
    event_bus: ComponentEventBus | None = None
    journal: ComponentJournal | None = None
    event_store: EventStore | None = None
    component_manager: ComponentController | None = None
    settings: Mapping[str, object] = field(default_factory=dict)


def normalize_component_id(component_id: str) -> str:
    normalized = component_id.strip().lower()
    if not normalized:
        raise ValueError("component_id must not be empty.")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    if any(char not in allowed for char in normalized):
        raise ValueError("component_id may only contain lowercase letters, digits, '-' and '_'.")
    return normalized
