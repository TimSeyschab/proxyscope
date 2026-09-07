from __future__ import annotations

from proxyscope.contracts.shortcuts import SYSTEM_SHORTCUTS, ShortcutDefinition, _normalize_key


class ShortcutRegistry:
    def __init__(self) -> None:
        self._shortcuts_by_component: dict[str, tuple[ShortcutDefinition, ...]] = {}

    def register_component(self, component_id: str, shortcuts: tuple[ShortcutDefinition, ...]) -> None:
        if component_id in self._shortcuts_by_component:
            raise ValueError(f"Shortcuts already registered for component: {component_id}")
        self._validate(shortcuts)
        self._shortcuts_by_component[component_id] = shortcuts

    def register(self, component_id: str, shortcut: ShortcutDefinition) -> None:
        existing = self._shortcuts_by_component.get(component_id, ())
        self._validate((shortcut,))
        self._shortcuts_by_component[component_id] = (*existing, shortcut)

    def unregister_component(self, component_id: str) -> None:
        self._shortcuts_by_component.pop(component_id, None)

    def resolve(self, key: str) -> ShortcutDefinition | None:
        normalized_key = _normalize_key(key)
        candidates = [shortcut for shortcut in self.list_shortcuts() if shortcut.key == normalized_key]
        if not candidates:
            return None
        return max(candidates, key=lambda shortcut: shortcut.priority)

    def list_shortcuts(self) -> tuple[ShortcutDefinition, ...]:
        return tuple(shortcut for shortcuts in self._shortcuts_by_component.values() for shortcut in shortcuts)

    def build_help_text(self) -> str:
        lines = ["Shortcuts"]
        for shortcut in self.list_shortcuts():
            lines.append(f"  {shortcut.key:<28} {shortcut.label}")
        return "\n".join(lines)

    def _validate(self, shortcuts: tuple[ShortcutDefinition, ...]) -> None:
        existing = self.list_shortcuts()
        seen: set[str] = set()
        for shortcut in shortcuts:
            key = _normalize_key(shortcut.key)
            if key in SYSTEM_SHORTCUTS:
                raise ValueError(f"Shortcut key is reserved: {key}")
            if key in seen:
                raise ValueError(f"Shortcut already registered: {key}")
            if any(item.key == key for item in existing):
                raise ValueError(f"Shortcut already registered: {key}")
            seen.add(key)


__all__ = ["SYSTEM_SHORTCUTS", "ShortcutDefinition", "ShortcutRegistry"]
