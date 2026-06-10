from collections.abc import Callable, Iterable
from dataclasses import dataclass

from proxyscope.application.services import RuntimeApplicationServices

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
        parts = normalized.split()
        command = self._by_name.get(parts[0].lower())
        if command is None:
            return None
        return command.handler(parts[1:])

    def contains(self, command_line: str, *, command_name: str) -> bool:
        normalized = command_line.strip()
        if not normalized:
            return False
        command = self._by_name.get(normalized.split()[0].lower())
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


def create_runtime_command_registry(
    services: RuntimeApplicationServices,
    *,
    request_shutdown: Callable[[], None] | None,
    on_cache_toggle: Callable[[], None] | None,
    on_schedule_policy_edit: Callable[[str], None],
) -> CommandRegistry:
    registry = CommandRegistry()

    def runtime_command(name: str, arguments: list[str]) -> CommandExecutionResult:
        command = " ".join((name, *arguments))
        result = services.runtime_commands.execute(
            command,
            on_cache_toggle=on_cache_toggle,
            on_schedule_policy_edit=on_schedule_policy_edit,
        )
        return CommandExecutionResult(
            status_message=result.status_message,
            updated_log_level=result.updated_log_level,
        )

    commands = [
        CommandDefinition(
            "help",
            lambda _args: CommandExecutionResult(registry.build_help_summary()),
            "Show this help dialog.",
            aliases=("?",),
            usage="help",
        ),
        CommandDefinition(
            "clear",
            lambda _args: CommandExecutionResult(services.requests.clear(), requests_changed=True),
            "Clear the captured request list.",
        ),
        CommandDefinition(
            "sites",
            lambda _args: CommandExecutionResult(services.requests.top_sites_summary()),
            "Show the busiest hosts.",
        ),
        CommandDefinition(
            "filter",
            lambda args: CommandExecutionResult(services.requests.apply_filter(args), requests_changed=True),
            "Filter requests by host, method, status, or text.",
            usage="filter ...",
        ),
        CommandDefinition(
            "find",
            lambda args: CommandExecutionResult(services.requests.find(args), requests_changed=True),
            "Shortcut for full-text request filtering.",
            usage="find <text>",
        ),
        CommandDefinition(
            "export",
            lambda args: CommandExecutionResult(services.sessions.export(args)),
            "Export the current request list.",
            usage="export <json|har> <path>",
        ),
        CommandDefinition(
            "session",
            lambda args: CommandExecutionResult(
                services.sessions.session(args),
                requests_changed=bool(args and args[0].lower() == "load"),
            ),
            "Save or load a captured session.",
            usage="session <save|load> <path>",
        ),
    ]
    for name, aliases, usage, help_text in (
        ("loglevel", (), "loglevel <LEVEL>", "Show or change the runtime log level."),
        ("mitm", (), "mitm ...", "Show or update MITM settings."),
        ("whitelist", ("wl",), "whitelist ...", "Inspect or change the logging whitelist."),
        ("cache", (), "cache ...", "Inspect or toggle cache invalidation."),
        ("config", (), "config ...", "Show, save, or reload runtime config."),
        ("policy", ("pol",), "policy ...", "Manage editor and static-response rules."),
    ):
        commands.append(
            CommandDefinition(
                name,
                lambda args, command_name=name: runtime_command(command_name, args),
                help_text,
                aliases=aliases,
                usage=usage,
            )
        )

    def quit_application(_arguments: list[str]) -> CommandExecutionResult:
        if request_shutdown is not None:
            request_shutdown()
        return CommandExecutionResult(status_message="Shutting down server...", should_exit=True)

    commands.append(
        CommandDefinition(
            "quit",
            quit_application,
            "Stop the proxy.",
            aliases=("exit", "q"),
            usage="quit",
        )
    )
    for command in commands:
        registry.register(command)
    return registry
