from proxyscope.contracts.commands import CommandDefinition, CommandExecutionResult
from proxyscope.contracts.components import ComponentContribution
from proxyscope.contracts.shortcuts import ShortcutDefinition

from .service import MockServerService


class MockServerComponent:
    def __init__(self, service: MockServerService) -> None:
        self._service = service

    def management_commands(self) -> tuple[CommandDefinition, ...]:
        # Scenario management remains available while traffic mocking is disabled.
        return (
            CommandDefinition(
                "mock",
                lambda arguments: CommandExecutionResult(self._service.execute(arguments)),
                "Manage mock scenarios.",
                usage="mock <list|enable|disable|export|import|scenario ...>",
            ),
        )

    def contribution(self) -> ComponentContribution:
        return ComponentContribution(
            component_id="mockserver",
            display_name="Mock server",
            shortcuts=(ShortcutDefinition("shift+m", "Mocks", "mock list"),),
            event_handlers=(self._service.handle_event,),
            on_activate=self._service.activate,
            on_deactivate=self._service.deactivate,
        )
