import shlex
from collections.abc import Callable, Iterable

from proxyscope.contracts.commands import CommandDefinition, CommandExecutionResult

DEFAULT_COMPONENT_ID = "default"
# These names belong to the built-in runtime lifecycle and help commands. Only
# the Core component may register them through ComponentManager.
RESERVED_COMMAND_NAMES: frozenset[str] = frozenset({"help", "?", "quit", "exit", "q"})
CommandHandler = Callable[[list[str]], "CommandExecutionResult"]


class CommandRegistry:
    def __init__(
        self,
        commands: Iterable[CommandDefinition] = (),
        *,
        reserved_names: Iterable[str] = (),
    ) -> None:
        self._commands: list[CommandDefinition] = []
        self._by_name: dict[str, CommandDefinition] = {}
        self._owner_by_name: dict[str, str] = {}
        self._names_by_component: dict[str, set[str]] = {}
        self._reserved_names = set(RESERVED_COMMAND_NAMES)
        self._reserved_names.update(_normalize_name(name) for name in reserved_names)
        for command in commands:
            self.register(command)

    def register(
        self,
        command: CommandDefinition,
        *,
        component_id: str = DEFAULT_COMPONENT_ID,
        allow_reserved: bool = False,
    ) -> None:
        names = (command.name, *command.aliases)
        normalized = tuple(_normalize_name(name) for name in names)
        if any(not name for name in normalized):
            raise ValueError("Command names and aliases must not be empty.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Command names and aliases must be unique.")
        reserved = next((name for name in normalized if name in self._reserved_names), None)
        if reserved is not None and not allow_reserved:
            raise ValueError(f"Command name or alias is reserved: {reserved}")
        duplicate = next((name for name in normalized if name in self._by_name), None)
        if duplicate is not None:
            raise ValueError(f"Command name or alias already registered: {duplicate}")
        normalized_component_id = _normalize_component_id(component_id)
        self._commands.append(command)
        self._names_by_component.setdefault(normalized_component_id, set()).update(normalized)
        for name in normalized:
            self._by_name[name] = command
            self._owner_by_name[name] = normalized_component_id

    def register_component(
        self,
        component_id: str,
        commands: Iterable[CommandDefinition],
        *,
        allow_reserved: bool = False,
    ) -> None:
        normalized_component_id = _normalize_component_id(component_id)
        if normalized_component_id in self._names_by_component:
            raise ValueError(f"Commands already registered for component: {normalized_component_id}")
        self._names_by_component[normalized_component_id] = set()
        try:
            for command in commands:
                self.register(command, component_id=normalized_component_id, allow_reserved=allow_reserved)
        except Exception:
            self.unregister_component(normalized_component_id)
            raise

    def unregister_component(self, component_id: str) -> None:
        normalized_component_id = _normalize_component_id(component_id)
        names = self._names_by_component.pop(normalized_component_id, set())
        if not names:
            return
        removed_commands = {self._by_name[name] for name in names if name in self._by_name}
        for name in names:
            self._by_name.pop(name, None)
            self._owner_by_name.pop(name, None)
        self._commands = [command for command in self._commands if command not in removed_commands]

    def dispatch(self, command_line: str) -> CommandExecutionResult | None:
        normalized = command_line.strip()
        if not normalized:
            return None
        try:
            parts = shlex.split(normalized)
        except ValueError as exc:
            return CommandExecutionResult(status_message=f"Invalid command syntax: {exc}")
        if not parts:
            return None
        command = self._by_name.get(parts[0].lower())
        if command is None:
            return None
        return command.handler(parts[1:])

    def contains(self, command_line: str, *, command_name: str) -> bool:
        normalized = command_line.strip()
        if not normalized:
            return False
        try:
            parts = shlex.split(normalized)
        except ValueError:
            return False
        if not parts:
            return False
        command = self._by_name.get(parts[0].lower())
        return command is not None and command.name == command_name

    def build_help_summary(self) -> str:
        usages = [command.usage or command.name for command in self._commands if command.show_in_help]
        return "Commands: " + " | ".join(usages)

    def build_help_text(self) -> str:
        lines = ["Commands"]
        for command in self._commands:
            if not command.show_in_help:
                continue
            names = ", ".join((command.name, *command.aliases))
            usage = command.usage or names
            lines.append(f"  {usage:<28} {command.help_text}")
        return "\n".join(lines)


def _normalize_name(name: str) -> str:
    return name.strip().lower()


def _normalize_component_id(component_id: str) -> str:
    normalized = component_id.strip().lower()
    if not normalized:
        raise ValueError("component_id must not be empty.")
    return normalized
