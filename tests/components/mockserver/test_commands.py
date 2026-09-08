import json

import pytest

from proxyscope.application.events import EventBus
from proxyscope.application.traffic_rules import TrafficRuleAdministrationService
from proxyscope.components.mockserver import MockServerService
from proxyscope.contracts.events import MockResponseServed, TrafficRuleApplied


def test_scenario_commands_toggle_exclusively_and_roundtrip_files(tmp_path):
    bus = EventBus()
    TrafficRuleAdministrationService(event_bus=bus)
    saved = []
    service = MockServerService(event_bus=bus, on_scenarios_change=saved.append)
    assert service.execute([]) == "Mocks: none"
    assert service.execute(["scenario", "add", "one"]) == "Mock scenario added: one"
    assert service.execute(["scenario", "add", "two", "Second", "scenario"]) == "Mock scenario added: two"
    assert service.execute(["scenario", "add", "one"]).startswith("Mock scenario already exists")
    assert service.execute(["enable", "missing"]) == "Mock scenario not found: missing"
    service.activate()
    service.execute(["scenario", "enable", "one"])
    service.execute(["enable", "two"])
    assert [scenario.enabled for scenario in service.store.list_scenarios()] == [False, True]
    assert "two (enabled)" in service.execute(["scenario", "list"])
    service.execute(["scenario", "disable", "two"])
    assert not any(scenario.enabled for scenario in service.store.list_scenarios())
    path = str(tmp_path / "mocks.json")
    assert service.execute(["export", path]) == f"Mock scenarios exported: {path}"
    restored = MockServerService()
    assert restored.execute(["import", path]) == f"Mock scenarios imported: {path}"
    assert restored.store.list_scenarios() == service.store.list_scenarios()
    assert restored.execute(["unknown"]).startswith("Usage: mock")
    assert saved[-1] == service.store.serialize()


@pytest.mark.parametrize("payload", [[], {}, {"scenarios": {}}])
def test_invalid_import_preserves_existing_scenarios(tmp_path, payload):
    service = MockServerService()
    service.execute(["scenario", "add", "existing"])
    before = service.store.list_scenarios()
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload))
    assert service.import_from(str(path)) == "Mock import failed: expected a scenarios array."
    assert service.store.list_scenarios() == before


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("kind", ["unrelated", "rewrite", "unknown-rule", "missing-status", "served"])
def test_only_active_mock_response_events_are_forwarded(tmp_path, active, kind):
    bus = EventBus()
    TrafficRuleAdministrationService(event_bus=bus)
    events = []
    bus.subscribe(events.append)
    service = MockServerService(event_bus=bus)
    path = tmp_path / "mocks.json"
    path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "id": "demo",
                        "enabled": True,
                        "responses": [{"id": "r", "method": "GET", "url": "http://api.test"}],
                    }
                ]
            }
        )
    )
    service.import_from(str(path))
    if active:
        service.activate()
    event = (
        object()
        if kind == "unrelated"
        else TrafficRuleApplied(
            rule_id="missing" if kind == "unknown-rule" else "mockserver:demo:r",
            summary="request modified" if kind == "rewrite" else "static response",
            status_code=None if kind == "missing-status" else 200,
        )
    )
    service.handle_event(event)
    forwarded = [item for item in events if isinstance(item, MockResponseServed)]
    assert len(forwarded) == int(active and kind == "served")
    if forwarded:
        assert forwarded[0].scenario_id == "demo"
        assert forwarded[0].status_code == 200
