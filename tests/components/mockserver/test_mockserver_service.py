import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from proxyscope.adapters.events import EventBusAdapter
from proxyscope.application.events import EventBus
from proxyscope.application.processing.models import ExchangeRequest
from proxyscope.application.traffic_rules import TrafficRuleEngine, TrafficRuleStore
from proxyscope.application.traffic_rules.events import TrafficRuleEventHandler
from proxyscope.components.mockserver import (
    MockResponse,
    MockScenario,
    MockScenarioStore,
    MockServerService,
    mockserver_configuration_from_payload,
    mockserver_configuration_payload,
)


def _service(store: MockScenarioStore, *, persisted: list[tuple[dict[str, object], ...]] | None = None) -> tuple[MockServerService, TrafficRuleStore]:
    bus = EventBus()
    rules = TrafficRuleStore()
    adapter = EventBusAdapter(bus)
    bus.subscribe(TrafficRuleEventHandler(rules, adapter, on_change=None if persisted is None else persisted.append))
    return MockServerService(store, event_bus=adapter), rules


def _store(*, enabled: bool = True) -> MockScenarioStore:
    store = MockScenarioStore()
    store.add(
        MockScenario(
            "offline",
            "Offline",
            enabled=enabled,
            responses=(MockResponse("items", "GET", "https://api.test/items", 503, "Offline", body="unavailable"),),
        )
    )
    return store


def test_component_derives_nonpersistent_traffic_rules_on_activation() -> None:
    persisted: list[tuple[dict[str, object], ...]] = []
    service, rules = _service(_store(), persisted=persisted)
    request = ExchangeRequest("GET", "https://api.test/items", "/items", {})

    assert TrafficRuleEngine(rules).prepare_request(request)[1] is None
    service.activate()

    response = TrafficRuleEngine(rules).prepare_request(request)[1]
    assert response is not None
    assert response.status_code == 503
    assert response.body == b"unavailable"
    assert rules.get("mockserver:offline:items") is not None
    assert persisted == []

    service.deactivate()
    assert TrafficRuleEngine(rules).prepare_request(request)[1] is None


def test_mock_configuration_roundtrips_without_global_rule_references() -> None:
    store = _store()
    payload = mockserver_configuration_payload(store)

    assert "rule_ids" not in json.dumps(payload)
    assert mockserver_configuration_from_payload(payload).list_scenarios() == store.list_scenarios()


def test_mockserver_schema_and_parser_validate_static_responses() -> None:
    schema_path = Path(__file__).resolve().parents[3] / "proxyscope" / "components" / "mockserver" / "config.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    payload = {"scenarios": [{"id": "demo", "responses": [{"id": "health", "method": "GET", "url": "https://api.test/health"}]}]}

    assert list(Draft202012Validator(schema).iter_errors(payload)) == []
    assert mockserver_configuration_from_payload(payload).list_scenarios()
    with pytest.raises(ValueError, match="unknown field"):
        mockserver_configuration_from_payload({"scenarios": [{"id": "demo", "unexpected": True}]})
    with pytest.raises(ValueError, match="responses"):
        mockserver_configuration_from_payload({"scenarios": [{"id": "demo", "responses": {}}]})
