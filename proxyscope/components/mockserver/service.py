from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace

from proxyscope.contracts.events import MockResponseServed, RuntimeEvent, TrafficRuleApplied
from proxyscope.contracts.ports import ComponentEventBus
from proxyscope.contracts.traffic_rules import RespondAction, RulePhase, TrafficMatch, TrafficRule
from proxyscope.contracts.traffic_rules.events import (
    TrafficRuleScope,
    TrafficRuleScopeUpdateRequested,
    TrafficRulesResult,
    TrafficRulesSnapshotRequested,
    TrafficRulesUpdateRequested,
)


@dataclass(frozen=True)
class MockResponse:
    response_id: str
    method: str
    url: str
    status_code: int = 200
    reason: str = "OK"
    headers: tuple[tuple[str, str], ...] = ()
    body: str = ""

    def __post_init__(self) -> None:
        if not self.response_id.strip() or not self.method.strip() or not self.url.strip():
            raise ValueError("Mock response ID, method, and URL must not be empty.")
        if not 100 <= self.status_code <= 599:
            raise ValueError("Mock response status must be in range 100..599.")


@dataclass(frozen=True)
class MockScenario:
    scenario_id: str
    name: str
    enabled: bool = False
    responses: tuple[MockResponse, ...] = ()


class MockScenarioStore:
    def __init__(self) -> None:
        self._scenarios: dict[str, MockScenario] = {}

    def add(self, scenario: MockScenario) -> None:
        if scenario.scenario_id in self._scenarios:
            raise ValueError(f"Mock scenario already exists: {scenario.scenario_id}")
        self._scenarios[scenario.scenario_id] = scenario

    def set_enabled(self, scenario_id: str, *, enabled: bool) -> bool:
        if scenario_id not in self._scenarios:
            return False
        if enabled:
            self._scenarios = {
                identifier: replace(scenario, enabled=identifier == scenario_id)
                for identifier, scenario in self._scenarios.items()
            }
        else:
            self._scenarios[scenario_id] = replace(self._scenarios[scenario_id], enabled=False)
        return True

    def list_scenarios(self) -> tuple[MockScenario, ...]:
        return tuple(self._scenarios.values())

    def response_for_rule(self, rule_id: str) -> tuple[str, MockResponse] | None:
        for scenario in self._scenarios.values():
            for response in scenario.responses:
                if _rule_id(scenario.scenario_id, response.response_id) == rule_id:
                    return scenario.scenario_id, response
        return None

    def serialize(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "id": scenario.scenario_id,
                "name": scenario.name,
                "enabled": scenario.enabled,
                "responses": [
                    {
                        "id": response.response_id,
                        "method": response.method,
                        "url": response.url,
                        "status": response.status_code,
                        "reason": response.reason,
                        "headers": dict(response.headers),
                        "body": response.body,
                    }
                    for response in scenario.responses
                ],
            }
            for scenario in self._scenarios.values()
        )


class MockServerService:
    def __init__(
        self,
        store: MockScenarioStore | None = None,
        *,
        event_bus: ComponentEventBus | None = None,
        on_scenarios_change: Callable[[tuple[dict[str, object], ...]], None] | None = None,
    ) -> None:
        self._store = store or MockScenarioStore()
        self._active = False
        self._event_bus = event_bus
        self._on_scenarios_change = on_scenarios_change

    @property
    def store(self) -> MockScenarioStore:
        return self._store

    def activate(self) -> None:
        self._active = True
        self._sync_derived_rules()

    def deactivate(self) -> None:
        self._active = False
        self._sync_rule_scope()

    @property
    def active(self) -> bool:
        return self._active

    def handle_event(self, event: object) -> None:
        if not self._active or not isinstance(event, TrafficRuleApplied) or event.summary != "static response":
            return
        matched = self._store.response_for_rule(event.rule_id)
        if matched is None or event.status_code is None or self._event_bus is None:
            return
        scenario_id, _ = matched
        self._event_bus.publish(
            MockResponseServed(
                request_id=event.request_id,
                rule_id=event.rule_id,
                scenario_id=scenario_id,
                status_code=event.status_code,
            )
        )

    def execute(self, arguments: list[str]) -> str:
        if not arguments or arguments == ["list"] or arguments == ["scenario", "list"]:
            scenarios = self._store.list_scenarios()
            return "Mocks: " + (
                ", ".join(f"{item.scenario_id} ({'enabled' if item.enabled else 'disabled'})" for item in scenarios)
                or "none"
            )
        if len(arguments) >= 3 and arguments[:2] == ["scenario", "add"]:
            return self._add_scenario(arguments[2], " ".join(arguments[3:]) or arguments[2])
        if len(arguments) == 2 and arguments[0] in {"enable", "disable"}:
            if not self._store.set_enabled(arguments[1], enabled=arguments[0] == "enable"):
                return f"Mock scenario not found: {arguments[1]}"
            self._changed_scenarios()
            return f"Mock scenario {arguments[0]}d: {arguments[1]}"
        if len(arguments) == 3 and arguments[:2] in (["scenario", "enable"], ["scenario", "disable"]):
            return self.execute([arguments[1], arguments[2]])
        if len(arguments) == 2 and arguments[0] == "export":
            return self.export_to(arguments[1])
        if len(arguments) == 2 and arguments[0] == "import":
            return self.import_from(arguments[1])
        return "Usage: mock <list|enable|disable|export|import|scenario list|scenario add|scenario enable|scenario disable> [args]"

    def export_to(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as output:
            json.dump({"scenarios": list(self._store.serialize())}, output, indent=2, ensure_ascii=True)
            output.write("\n")
        return f"Mock scenarios exported: {path}"

    def import_from(self, path: str) -> str:
        with open(path, encoding="utf-8") as source:
            payload = json.load(source)
        if not isinstance(payload, dict) or not isinstance(payload.get("scenarios"), list):
            return "Mock import failed: expected a scenarios array."
        self._store = scenario_store_from_config(tuple(item for item in payload["scenarios"] if isinstance(item, dict)))
        self._changed_scenarios()
        return f"Mock scenarios imported: {path}"

    def _add_scenario(self, scenario_id: str, name: str) -> str:
        try:
            self._store.add(MockScenario(scenario_id, name))
        except ValueError as exc:
            return str(exc)
        self._changed_scenarios()
        return f"Mock scenario added: {scenario_id}"

    def _sync_derived_rules(self) -> None:
        if self._event_bus is None:
            raise ValueError("Traffic rule management is unavailable.")
        derived = self._derived_rules()
        existing = {rule.rule_id for rule in self._rule_result(TrafficRulesSnapshotRequested()).rules}
        additions = tuple(rule for rule in derived if rule.rule_id not in existing)
        replacements = tuple(rule for rule in derived if rule.rule_id in existing)
        if additions:
            self._rule_result(TrafficRulesUpdateRequested(operation="add", rules=additions, persist=False))
        if replacements:
            self._rule_result(TrafficRulesUpdateRequested(operation="replace", rules=replacements, persist=False))
        self._sync_rule_scope()

    def _derived_rules(self) -> tuple[TrafficRule, ...]:
        return tuple(
            TrafficRule(
                rule_id=_rule_id(scenario.scenario_id, response.response_id),
                name=f"{scenario.name}: {response.response_id}",
                enabled=True,
                priority=0,
                phase=RulePhase.RESPOND,
                match=TrafficMatch(methods=(response.method,), url=response.url),
                action=RespondAction(
                    response.status_code,
                    response.reason,
                    response.headers,
                    response.body.encode("utf-8"),
                ),
            )
            for scenario in self._store.list_scenarios()
            for response in scenario.responses
        )

    def _sync_rule_scope(self) -> None:
        if self._event_bus is not None:
            self._rule_result(TrafficRuleScopeUpdateRequested(scope=self._rule_scope()))

    def _rule_scope(self) -> TrafficRuleScope:
        rule_ids = tuple(rule.rule_id for rule in self._derived_rules())
        active = tuple(
            _rule_id(scenario.scenario_id, response.response_id)
            for scenario in self._store.list_scenarios()
            if self._active and scenario.enabled
            for response in scenario.responses
        )
        return TrafficRuleScope(owner_id="mockserver", rule_ids=rule_ids, active_rule_ids=active)

    def _rule_result(self, request: RuntimeEvent) -> TrafficRulesResult:
        if self._event_bus is None:
            raise ValueError("Traffic rule management is unavailable.")
        results: list[TrafficRulesResult] = []

        def receive(event: RuntimeEvent) -> None:
            if isinstance(event, TrafficRulesResult) and event.correlation_id == request.event_id:
                results.append(event)

        self._event_bus.subscribe(receive)
        try:
            self._event_bus.publish(request)
        finally:
            self._event_bus.unsubscribe(receive)
        if not results:
            raise ValueError("Traffic rule request was not confirmed.")
        if results[0].error is not None:
            raise ValueError(results[0].error)
        return results[0]

    def _changed_scenarios(self) -> None:
        if self._active:
            self._sync_derived_rules()
        else:
            self._sync_rule_scope()
        if self._on_scenarios_change is not None:
            self._on_scenarios_change(self._store.serialize())


def scenario_store_from_config(values: tuple[dict[str, object], ...]) -> MockScenarioStore:
    store = MockScenarioStore()
    for value in values:
        _reject_unknown_fields(value, {"id", "name", "enabled", "responses"}, "Mock scenario")
        scenario_id = _required_string(value.get("id"), "Mock scenario ID")
        name = _required_string(value.get("name", scenario_id), "Mock scenario name")
        enabled = value.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("Mock scenario enabled must be a boolean.")
        raw_responses = value.get("responses", [])
        if not isinstance(raw_responses, list) or not all(isinstance(item, dict) for item in raw_responses):
            raise ValueError("Mock scenario responses must be an array of objects.")
        responses = tuple(_response_from_config(item) for item in raw_responses)
        if len({response.response_id for response in responses}) != len(responses):
            raise ValueError("Mock response IDs must be unique within a scenario.")
        store.add(MockScenario(scenario_id, name, enabled, responses))
    return store


def _response_from_config(value: dict[str, object]) -> MockResponse:
    _reject_unknown_fields(value, {"id", "method", "url", "status", "reason", "headers", "body"}, "Mock response")
    headers = value.get("headers", {})
    if not isinstance(headers, dict) or not all(isinstance(name, str) and isinstance(item, str) for name, item in headers.items()):
        raise ValueError("Mock response headers must be an object of strings.")
    status = value.get("status", 200)
    if not isinstance(status, int) or isinstance(status, bool):
        raise ValueError("Mock response status must be an integer.")
    body = value.get("body", "")
    if not isinstance(body, str):
        raise ValueError("Mock response body must be a string.")
    return MockResponse(
        response_id=_required_string(value.get("id"), "Mock response ID"),
        method=_required_string(value.get("method"), "Mock response method").upper(),
        url=_required_string(value.get("url"), "Mock response URL"),
        status_code=status,
        reason=_required_string(value.get("reason", "OK"), "Mock response reason"),
        headers=tuple(headers.items()),
        body=body,
    )


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()


def _reject_unknown_fields(value: dict[str, object], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{field} contains unknown field(s): {', '.join(unknown)}.")


def _rule_id(scenario_id: str, response_id: str) -> str:
    return f"mockserver:{scenario_id}:{response_id}"


__all__ = ["MockResponse", "MockScenario", "MockScenarioStore", "MockServerService", "scenario_store_from_config"]
