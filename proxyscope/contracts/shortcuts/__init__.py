from __future__ import annotations

from dataclasses import dataclass

SYSTEM_SHORTCUTS: frozenset[str] = frozenset({":", "esc", "tab", "shift+tab"})


@dataclass(frozen=True)
class ShortcutDefinition:
    key: str
    label: str
    command: str
    priority: int = 0
    show_in_footer: bool = False

    def __post_init__(self) -> None:
        if _normalize_key(self.key) != self.key:
            raise ValueError("shortcut key must already be normalized.")
        if not self.label.strip():
            raise ValueError("shortcut label must not be empty.")
        if not self.command.strip():
            raise ValueError("shortcut command must not be empty.")


def _normalize_key(key: str) -> str:
    normalized = key.strip().lower()
    aliases = {"escape": "esc"}
    normalized = aliases.get(normalized, normalized)
    if not normalized:
        raise ValueError("shortcut key must not be empty.")
    return normalized
