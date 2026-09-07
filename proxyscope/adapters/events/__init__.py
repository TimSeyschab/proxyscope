from proxyscope.application.events import EventBus
from proxyscope.contracts.events import RuntimeEvent
from proxyscope.contracts.ports import EventHandler


class EventBusAdapter:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    def publish(self, event: RuntimeEvent) -> None:
        self._event_bus.publish(event)

    def subscribe(self, handler: EventHandler) -> None:
        self._event_bus.subscribe(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        self._event_bus.unsubscribe(handler)


__all__ = ["EventBusAdapter"]
