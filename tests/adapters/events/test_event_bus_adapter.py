from proxyscope.adapters.events import EventBusAdapter
from proxyscope.application.components import ComponentContribution, ComponentManager
from proxyscope.application.events import EventBus, TrafficRuleApplied


def test_component_subscription_lifecycle_uses_shared_event_bus() -> None:
    bus = EventBus()
    adapter = EventBusAdapter(bus)
    observed = []
    handled = []
    bus.subscribe(observed.append)
    manager = ComponentManager(event_bus=adapter)
    manager.register(ComponentContribution("demo", "Demo", event_handlers=(handled.append,)), activate=False)
    event = TrafficRuleApplied(rule_id="one", summary="static response")

    manager.activate("demo")
    bus.publish(event)
    manager.deactivate("demo")
    adapter.publish(event)
    manager.activate("demo")
    adapter.publish(event)
    manager.deactivate("demo")

    assert sum(item is event for item in handled) == 2
    assert sum(item is event for item in observed) == 3
