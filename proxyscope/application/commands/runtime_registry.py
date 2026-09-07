from __future__ import annotations

from collections.abc import Callable

from proxyscope.application.commands.registry import CommandDefinition, CommandExecutionResult, CommandRegistry
from proxyscope.application.components import (
    CORE_COMPONENT_ID,
    ComponentContext,
    ComponentContribution,
)
from proxyscope.contracts.components import ComponentController


def create_core_runtime_component(
    context: ComponentContext,
    *,
    command_registry: CommandRegistry,
    request_shutdown: Callable[[], None] | None,
) -> ComponentContribution:
    return ComponentContribution(
        component_id=CORE_COMPONENT_ID,
        display_name="Core runtime",
        commands=(
            *_help_commands(command_registry),
            *context.commands,
            *_shutdown_commands(request_shutdown),
            *_component_commands(context.component_manager),
        ),
    )


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


def _component_commands(component_manager: ComponentController | None) -> tuple[CommandDefinition, ...]:
    def handle(arguments: list[str]) -> CommandExecutionResult:
        if component_manager is None:
            return CommandExecutionResult("Component manager is unavailable.")
        if not arguments or arguments[0] == "list":
            statuses = component_manager.list_statuses()
            return CommandExecutionResult("Components: " + ", ".join(f"{name} ({status})" for name, status in statuses))
        if len(arguments) != 2 or arguments[0] not in {"enable", "disable", "describe"}:
            return CommandExecutionResult("Usage: component <list|enable|disable|describe> [id]")
        action, component_id = arguments
        try:
            if action == "describe":
                return CommandExecutionResult(component_manager.describe(component_id))
            if action == "enable":
                component_manager.activate(component_id)
                return CommandExecutionResult(f"Component enabled: {component_id}")
            component_manager.deactivate(component_id)
            return CommandExecutionResult(f"Component disabled: {component_id}")
        except ValueError as exc:
            return CommandExecutionResult(str(exc))

    return (
        CommandDefinition(
            "component",
            handle,
            "List, describe, enable, or disable components.",
            usage="component <list|enable|disable|describe> [id]",
        ),
    )
