from collections.abc import Callable
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
    show_in_help: bool = True
