from dataclasses import replace

import pytest

from proxyscope.adapters.events import EventBusAdapter
from proxyscope.application.events import EventBus
from proxyscope.application.traffic_rules import TrafficRuleAdministrationService, TrafficRuleEngine, TrafficRuleStore
from proxyscope.application.traffic_rules.events import TrafficRuleEventHandler
from proxyscope.components.mockserver import MockResponse, MockScenario, MockScenarioStore, MockServerService
from proxyscope.contracts.exchanges import ExchangeRequest
from proxyscope.contracts.traffic_rules import RespondAction, RulePhase, TrafficMatch, TrafficRule
from proxyscope.contracts.traffic_rules.events import (
    TrafficRuleScope,
    TrafficRuleScopeUpdateRequested,
    TrafficRulesResult,
    TrafficRulesSnapshotRequested,
    TrafficRulesUpdateRequested,
)


def _rule(rule_id="one", *, enabled=True):
    return TrafficRule(rule_id, rule_id, enabled, 0, RulePhase.RESPOND, TrafficMatch(), RespondAction())


def _runtime():
    store = TrafficRuleStore()
    bus = EventBus()
    saved = []
    results = []
    bus.subscribe(TrafficRuleEventHandler(store, EventBusAdapter(bus), on_change=saved.append))
    bus.subscribe(lambda event: results.append(event) if isinstance(event, TrafficRulesResult) else None)
    return store, bus, saved, results


def test_add_replace_remove_and_snapshot_are_processed_by_event_handler():
    store, bus, saved, results = _runtime()
    add = TrafficRulesUpdateRequested(operation="add", rules=(_rule(),))
    bus.publish(add)
    assert store.get("one") == _rule()
    assert results[-1].correlation_id == add.event_id
    assert results[-1].error is None

    bus.publish(TrafficRulesUpdateRequested(operation="replace", rules=(_rule(enabled=False),)))
    assert store.list(scoped=True) == ()
    assert saved[-1][0]["enabled"] is False
    bus.publish(TrafficRulesSnapshotRequested())
    assert results[-1].rules == (_rule(enabled=False),)

    bus.publish(TrafficRulesUpdateRequested(operation="remove", rule_ids=("one",)))
    assert store.snapshot() == ()
    assert saved[-1] == ()
    assert len(saved) == 3


@pytest.mark.parametrize(
    "update",
    [
        TrafficRulesUpdateRequested(operation="add", rules=(_rule("new"), _rule())),
        TrafficRulesUpdateRequested(operation="replace", rules=(replace(_rule(), name="changed"), _rule("missing"))),
        TrafficRulesUpdateRequested(operation="remove", rule_ids=("one", "missing")),
        TrafficRulesUpdateRequested(operation="replace_all", rules=(_rule("duplicate"), _rule("duplicate"))),
    ],
)
def test_failed_batch_keeps_all_existing_rules_and_scope(update):
    store, bus, saved, results = _runtime()
    bus.publish(
        TrafficRulesUpdateRequested(
            operation="add",
            rules=(_rule(),),
            scope=TrafficRuleScope("mockserver", ("one",), ()),
        )
    )
    bus.publish(replace(update, scope=TrafficRuleScope("mockserver", ("one",), ("one",))))

    assert results[-1].error is not None
    assert results[-1].correlation_id == update.event_id
    assert store.snapshot() == (_rule(),)
    assert store.list(scoped=True) == ()
    assert len(saved) == 1


def test_scope_updates_preserve_global_rules_and_other_components():
    store, bus, saved, results = _runtime()
    bus.publish(
        TrafficRulesUpdateRequested(operation="add", rules=tuple(_rule(name) for name in ("global", "mock", "other")))
    )
    bus.publish(TrafficRuleScopeUpdateRequested(scope=TrafficRuleScope("mockserver", ("mock",), ("mock",))))
    bus.publish(TrafficRuleScopeUpdateRequested(scope=TrafficRuleScope("another", ("other",), ())))
    assert {rule.rule_id for rule in store.list(scoped=True)} == {"global", "mock"}

    bus.publish(TrafficRuleScopeUpdateRequested(scope=TrafficRuleScope("mockserver", ("mock",), ())))
    assert {rule.rule_id for rule in store.list(scoped=True)} == {"global"}
    bus.publish(TrafficRuleScopeUpdateRequested(scope=TrafficRuleScope("another", ("other",), ("other",))))
    assert {rule.rule_id for rule in store.list(scoped=True)} == {"global", "other"}
    assert len(saved) == 1
    assert all(result.error is None for result in results)


def test_administration_sends_mutations_through_shared_bus():
    bus = EventBus()
    events = []
    bus.subscribe(events.append)
    saved = []
    service = TrafficRuleAdministrationService(event_bus=EventBusAdapter(bus), on_change=saved.append)

    assert service.execute(["add", "respond", "one", "GET", "http://example.test", "200"]) == "Traffic rule added: one"
    assert service.execute(["disable", "one"]) == "Traffic rule disabled: one"
    assert service.execute(["remove", "one"]) == "Traffic rule removed: one"

    assert [event.operation for event in events if isinstance(event, TrafficRulesUpdateRequested)] == [
        "add",
        "replace",
        "remove",
    ]
    assert len(saved) == 3


def test_component_reactivation_uses_scope_events_without_engine_callback():
    store, bus, _, _ = _runtime()
    scenarios = MockScenarioStore()
    scenarios.add(
        MockScenario(
            "demo",
            "Demo",
            enabled=True,
            responses=(MockResponse("one", "GET", "http://example.test", body="mock"),),
        )
    )
    component = MockServerService(scenarios, event_bus=EventBusAdapter(bus))
    engine = TrafficRuleEngine(store)
    request = ExchangeRequest("GET", "http://example.test", "/", {})

    assert engine.prepare_request(request)[1] is None
    component.activate()
    assert engine.prepare_request(request)[1] is not None
    component.deactivate()
    assert engine.prepare_request(request)[1] is None
    component.activate()
    assert engine.prepare_request(request)[1] is not None


def test_component_does_not_assume_delivery_without_application_handler():
    component = MockServerService(event_bus=EventBusAdapter(EventBus()))
    with pytest.raises(ValueError, match="not confirmed"):
        component.activate()


def test_failed_persistence_does_not_commit_rule_or_scope_changes():
    store = TrafficRuleStore((_rule(),))
    bus = EventBus()
    results = []

    def fail_save(_rules):
        raise OSError("Cannot save rules")

    bus.subscribe(TrafficRuleEventHandler(store, EventBusAdapter(bus), on_change=fail_save))
    bus.subscribe(lambda event: results.append(event) if isinstance(event, TrafficRulesResult) else None)
    bus.publish(
        TrafficRulesUpdateRequested(
            operation="replace_all",
            rules=(_rule("replacement"),),
            scope=TrafficRuleScope("mockserver", ("one",), ()),
        )
    )

    assert results[-1].error == "Cannot save rules"
    assert store.snapshot() == (_rule(),)
    assert store.list(scoped=True) == (_rule(),)
