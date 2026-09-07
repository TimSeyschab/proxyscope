from __future__ import annotations

from collections.abc import Callable

from proxyscope.application.commands.registry import CommandDefinition, CommandExecutionResult
from proxyscope.application.services import RuntimeApplicationServices


class CoreCommandsAdapter:
    def __init__(
        self,
        services: RuntimeApplicationServices,
        *,
        on_cache_toggle: Callable[[], None] | None = None,
        management_commands: tuple[CommandDefinition, ...] = (),
    ) -> None:
        self.commands = (
            *_request_commands(services),
            *_session_commands(services),
            *_runtime_subcommands(
                services,
                on_cache_toggle=on_cache_toggle,
            ),
            *management_commands,
            *_traffic_rule_commands(services),
        )


def _request_commands(services: RuntimeApplicationServices) -> tuple[CommandDefinition, ...]:
    return (
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
    )


def _session_commands(services: RuntimeApplicationServices) -> tuple[CommandDefinition, ...]:
    return (
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
    )


def _runtime_subcommands(
    services: RuntimeApplicationServices,
    *,
    on_cache_toggle: Callable[[], None] | None,
) -> tuple[CommandDefinition, ...]:
    def runtime_command(name: str, arguments: list[str]) -> CommandExecutionResult:
        result = services.runtime_commands.execute_parts(
            [name, *arguments],
            on_cache_toggle=on_cache_toggle,
        )
        return CommandExecutionResult(
            status_message=result.status_message,
            updated_log_level=result.updated_log_level,
        )

    commands: list[CommandDefinition] = []
    for name, aliases, usage, help_text in (
        ("loglevel", (), "loglevel <LEVEL>", "Show or change the runtime log level."),
        ("mitm", (), "mitm ...", "Show or update MITM settings."),
        ("whitelist", ("wl",), "whitelist ...", "Inspect or change the logging whitelist."),
        ("cache", (), "cache ...", "Inspect or toggle cache invalidation."),
        ("config", (), "config ...", "Show, save, or reload runtime config."),
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
    return tuple(commands)


def _traffic_rule_commands(services: RuntimeApplicationServices) -> tuple[CommandDefinition, ...]:
    return (
        CommandDefinition(
            "rule",
            lambda arguments: CommandExecutionResult(services.traffic_rules.execute(arguments)),
            "Manage traffic response, rewrite, and header rules.",
            usage="rule <list|enable|disable|add|remove|test> ...",
        ),
    )
