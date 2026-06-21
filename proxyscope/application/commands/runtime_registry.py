from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, Callable

from proxyscope.application.commands.registry import CommandDefinition, CommandExecutionResult, CommandRegistry

if TYPE_CHECKING:
    from proxyscope.application.services import RuntimeApplicationServices


def create_runtime_command_registry(
    services: RuntimeApplicationServices,
    *,
    request_shutdown: Callable[[], None] | None,
    on_cache_toggle: Callable[[], None] | None,
    on_schedule_policy_edit: Callable[[str], None],
) -> CommandRegistry:
    registry = CommandRegistry()
    command_groups = (
        _help_commands(registry),
        _request_commands(services),
        _session_commands(services),
        _runtime_subcommands(
            services,
            on_cache_toggle=on_cache_toggle,
            on_schedule_policy_edit=on_schedule_policy_edit,
        ),
        _shutdown_commands(request_shutdown),
    )

    for command in chain.from_iterable(command_groups):
        registry.register(command)
    return registry


def _help_commands(registry: CommandRegistry) -> tuple[CommandDefinition, ...]:
    return (
        CommandDefinition(
            "help",
            lambda _args: CommandExecutionResult(registry.build_help_summary()),
            "Show this help dialog.",
            aliases=("?",),
            usage="help",
        ),
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
    on_schedule_policy_edit: Callable[[str], None],
) -> tuple[CommandDefinition, ...]:
    def runtime_command(name: str, arguments: list[str]) -> CommandExecutionResult:
        result = services.runtime_commands.execute_parts(
            [name, *arguments],
            on_cache_toggle=on_cache_toggle,
            on_schedule_policy_edit=on_schedule_policy_edit,
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
    return tuple(commands)


def _shutdown_commands(request_shutdown: Callable[[], None] | None) -> tuple[CommandDefinition, ...]:
    def quit_application(_arguments: list[str]) -> CommandExecutionResult:
        if request_shutdown is not None:
            request_shutdown()
        return CommandExecutionResult(status_message="Shutting down server...", should_exit=True)

    return (
        CommandDefinition(
            "quit",
            quit_application,
            "Stop the proxy.",
            aliases=("exit", "q"),
            usage="quit",
        ),
    )
