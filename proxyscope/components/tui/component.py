from proxyscope.contracts.components import ComponentContext, ComponentContribution
from proxyscope.contracts.events import RuntimeEvent, RuntimeStateSnapshot, RuntimeStateSnapshotRequested

from .app import ProxyscopeTui


class TuiComponent:
    """A read-only runtime view backed exclusively by component ports."""

    def __init__(self, context: ComponentContext) -> None:
        if context.event_bus is None:
            raise ValueError("TUI component requires an event bus.")
        if context.journal is None:
            raise ValueError("TUI component requires a journal.")
        self._event_bus = context.event_bus
        self._app = ProxyscopeTui(context.journal)

    def contribution(self) -> ComponentContribution:
        return ComponentContribution(
            component_id="tui",
            display_name="Terminal UI",
            event_handlers=(self.handle_event,),
            on_activate=self.request_runtime_snapshot,
        )

    def handle_event(self, event: RuntimeEvent) -> None:
        if isinstance(event, RuntimeStateSnapshot):
            self._app.update_runtime_snapshot(event)
            return
        self._app.handle_event(event)

    def request_runtime_snapshot(self) -> None:
        self._event_bus.publish(RuntimeStateSnapshotRequested())

    def run(self) -> None:
        self._app.run()

    @property
    def app(self) -> ProxyscopeTui:
        return self._app
