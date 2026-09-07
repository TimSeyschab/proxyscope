from __future__ import annotations

from collections.abc import Callable
from typing import cast

from proxyscope.application.commands.registry import CommandRegistry
from proxyscope.application.components.ports import ComponentEventBus, EventHandler
from proxyscope.application.events import ComponentDisabled, ComponentEnabled
from proxyscope.application.shortcuts import ShortcutRegistry
from proxyscope.contracts.components import (
    CORE_COMPONENT_ID,
    ComponentContext,
    ComponentContribution,
    normalize_component_id,
)


class ComponentRegistry:
    def __init__(self) -> None:
        self._contributions: dict[str, ComponentContribution] = {}

    def register(self, contribution: ComponentContribution) -> None:
        component_id = contribution.component_id
        if component_id in self._contributions:
            raise ValueError(f"Component already registered: {component_id}")
        self._contributions[component_id] = contribution

    def unregister(self, component_id: str) -> ComponentContribution | None:
        return self._contributions.pop(normalize_component_id(component_id), None)

    def get(self, component_id: str) -> ComponentContribution | None:
        return self._contributions.get(normalize_component_id(component_id))

    def list_contributions(self) -> tuple[ComponentContribution, ...]:
        return tuple(self._contributions.values())


class ComponentManager:
    def __init__(
        self,
        *,
        component_registry: ComponentRegistry | None = None,
        command_registry: CommandRegistry | None = None,
        shortcut_registry: ShortcutRegistry | None = None,
        event_bus: ComponentEventBus | None = None,
        on_status_change: Callable[[tuple[str, ...]], None] | None = None,
    ) -> None:
        self._component_registry = component_registry or ComponentRegistry()
        self._command_registry = command_registry or CommandRegistry()
        self._shortcut_registry = shortcut_registry or ShortcutRegistry()
        self._event_bus = event_bus
        self._on_status_change = on_status_change
        self._active_components: set[str] = set()
        self._event_handlers: dict[str, tuple[object, ...]] = {}
        self._request_middlewares: dict[str, tuple[object, ...]] = {}
        self._response_middlewares: dict[str, tuple[object, ...]] = {}

    @property
    def command_registry(self) -> CommandRegistry:
        return self._command_registry

    @property
    def shortcut_registry(self) -> ShortcutRegistry:
        return self._shortcut_registry

    def list_statuses(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (
                contribution.component_id,
                "active" if contribution.component_id in self._active_components else "disabled",
            )
            for contribution in self._component_registry.list_contributions()
        )

    def describe(self, component_id: str) -> str:
        contribution = self._component_registry.get(component_id)
        if contribution is None:
            return f"Component not found: {normalize_component_id(component_id)}"
        status = "active" if contribution.component_id in self._active_components else "disabled"
        return (
            f"{contribution.component_id} ({status}): commands={len(contribution.commands)}, "
            f"shortcuts={len(contribution.shortcuts)}, handlers={len(contribution.event_handlers)}, "
            f"request_middleware={len(contribution.request_middlewares)}, "
            f"response_middleware={len(contribution.response_middlewares)}"
        )

    def request_middlewares(self) -> tuple[object, ...]:
        return tuple(item for items in self._request_middlewares.values() for item in items)

    def response_middlewares(self) -> tuple[object, ...]:
        return tuple(item for items in self._response_middlewares.values() for item in items)

    def register(self, contribution: ComponentContribution, *, activate: bool = True) -> None:
        self._component_registry.register(contribution)
        if activate:
            try:
                self.activate(contribution.component_id)
            except Exception:
                self._component_registry.unregister(contribution.component_id)
                raise

    def activate(self, component_id: str) -> None:
        normalized = normalize_component_id(component_id)
        if normalized in self._active_components:
            return
        contribution = self._component_registry.get(normalized)
        if contribution is None:
            raise ValueError(f"Component not registered: {normalized}")
        registered_commands = False
        registered_shortcuts = False
        registered_handlers: tuple[object, ...] = ()
        try:
            self._command_registry.register_component(
                normalized,
                contribution.commands,
                allow_reserved=normalized == CORE_COMPONENT_ID,
            )
            registered_commands = True
            self._shortcut_registry.register_component(normalized, contribution.shortcuts)
            registered_shortcuts = True
            if self._event_bus is not None:
                for handler in contribution.event_handlers:
                    if not callable(handler):
                        raise ValueError("Component event handlers must be callable.")
                    self._event_bus.subscribe(cast(EventHandler, handler))
                registered_handlers = contribution.event_handlers
            self._event_handlers[normalized] = registered_handlers
            self._request_middlewares[normalized] = contribution.request_middlewares
            self._response_middlewares[normalized] = contribution.response_middlewares
            if contribution.on_activate is not None:
                contribution.on_activate()
            self._active_components.add(normalized)
            if self._event_bus is not None:
                self._event_bus.publish(ComponentEnabled(component_id=normalized))
            self._notify_status_change()
        except Exception:
            if self._event_bus is not None:
                for handler in registered_handlers:
                    self._event_bus.unsubscribe(cast(EventHandler, handler))
            self._event_handlers.pop(normalized, None)
            self._request_middlewares.pop(normalized, None)
            self._response_middlewares.pop(normalized, None)
            if registered_shortcuts:
                self._shortcut_registry.unregister_component(normalized)
            if registered_commands:
                self._command_registry.unregister_component(normalized)
            raise

    def deactivate(self, component_id: str) -> None:
        normalized = normalize_component_id(component_id)
        if normalized not in self._active_components:
            return
        if normalized == CORE_COMPONENT_ID:
            raise ValueError("Core component cannot be disabled.")
        contribution = self._component_registry.get(normalized)
        if contribution is not None and contribution.on_deactivate is not None:
            contribution.on_deactivate()
        for handler in self._event_handlers.pop(normalized, ()):
            if self._event_bus is not None:
                self._event_bus.unsubscribe(cast(EventHandler, handler))
        self._command_registry.unregister_component(normalized)
        self._shortcut_registry.unregister_component(normalized)
        self._request_middlewares.pop(normalized, None)
        self._response_middlewares.pop(normalized, None)
        self._active_components.remove(normalized)
        if self._event_bus is not None:
            self._event_bus.publish(ComponentDisabled(component_id=normalized))
        self._notify_status_change()

    def unregister(self, component_id: str) -> ComponentContribution | None:
        normalized = normalize_component_id(component_id)
        self.deactivate(normalized)
        return self._component_registry.unregister(normalized)

    def is_active(self, component_id: str) -> bool:
        return normalize_component_id(component_id) in self._active_components

    def _notify_status_change(self) -> None:
        if self._on_status_change is not None:
            self._on_status_change(
                tuple(component_id for component_id, status in self.list_statuses() if status == "active")
            )


__all__ = [
    "CORE_COMPONENT_ID",
    "ComponentContext",
    "ComponentContribution",
    "ComponentManager",
    "ComponentRegistry",
    "normalize_component_id",
]
