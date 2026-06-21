import shlex
from collections.abc import Callable, Iterable
from dataclasses import dataclass

CommandHandler = Callable[[list[str]], "CommandExecutionResult"]


@dataclass(frozen=True)
class CommandExecutionResult:
    status_message: str = ""
    should_exit: bool = False
    requests_changed: bool = False
    updated_log_level: int | None = None


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    handler: CommandHandler
    help_text: str
    aliases: tuple[str, ...] = ()
    usage: str | None = None


class CommandRegistry:
    def __init__(self, commands: Iterable[CommandDefinition] = ()) -> None:
        self._commands: list[CommandDefinition] = []
        self._by_name: dict[str, CommandDefinition] = {}
        for command in commands:
            self.register(command)

    def register(self, command: CommandDefinition) -> None:
        names = (command.name, *command.aliases)
        normalized = tuple(name.strip().lower() for name in names)
        if any(not name for name in normalized):
            raise ValueError("Command names and aliases must not be empty.")
        duplicate = next((name for name in normalized if name in self._by_name), None)
        if duplicate is not None:
            raise ValueError(f"Command name or alias already registered: {duplicate}")
        self._commands.append(command)
        for name in normalized:
            self._by_name[name] = command

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
        usages = [command.usage or command.name for command in self._commands]
        return "Commands: " + " | ".join(usages)

    def build_help_text(self) -> str:
        lines = ["Commands"]
        for command in self._commands:
            names = ", ".join((command.name, *command.aliases))
            usage = command.usage or names
            lines.append(f"  {usage:<28} {command.help_text}")
        return "\n".join(lines)
