import json
from pathlib import Path

from jsonschema import Draft202012Validator

from proxyscope.application.configuration import (
    ConfigDocument,
    ConfigValidationError,
    RuntimeSettings,
    parse_config_payload,
    serialize_config_document,
)
from proxyscope.application.events import EventBus, TrafficRuleApplied
from proxyscope.application.processing.models import ExchangeRequest, ExchangeResponse
from proxyscope.application.traffic_rules import (
    HeaderRemoveAction,
    HeaderReplaceAction,
    HeaderSetAction,
    OpenEditorAction,
    RegexBodyRewriteAction,
    RespondAction,
    RulePhase,
    TrafficMatch,
    TrafficRule,
    TrafficRuleAdministrationService,
    TrafficRuleEngine,
    TrafficRuleStore,
    parse_rule,
    serialize_rule,
)


def _request(*, body: bytes = b"", headers: dict[str, str] | None = None) -> ExchangeRequest:
    return ExchangeRequest("GET", "https://api.test/items", "/items", headers or {"Content-Type": "text/plain"}, body)


def _rule(rule_id: str, phase: RulePhase, action, *, priority: int = 0) -> TrafficRule:
    return TrafficRule(rule_id, rule_id, True, priority, phase, TrafficMatch(methods=("GET",), url="https://api.test/items"), action)


def test_request_and_response_regex_rules_apply_in_priority_order() -> None:
    engine = TrafficRuleEngine(TrafficRuleStore((
        _rule("request", RulePhase.REQUEST, RegexBodyRewriteAction("one", "two")),
        _rule("response-low", RulePhase.RESPONSE, RegexBodyRewriteAction("two", "three")),
        _rule("response-high", RulePhase.RESPONSE, RegexBodyRewriteAction("three", "four"), priority=10),
    )))

    request, static = engine.prepare_request(_request(body=b"one"))
    response = engine.process_response(request, ExchangeResponse(200, "OK", {"Content-Type": "text/plain"}, b"two"), request_id=1)

    assert static is None
    assert request.body == b"two"
    assert response.body == b"three"
    assert response.headers["Content-Length"] == "5"


def test_respond_short_circuits_and_response_headers_are_rewritten() -> None:
    engine = TrafficRuleEngine(TrafficRuleStore((
        _rule("respond", RulePhase.RESPOND, RespondAction(201, "Created", (("X-Source", "mock"),), b"body")),
        _rule("header", RulePhase.RESPONSE, HeaderReplaceAction("X-Source", "rule")),
        _rule("set", RulePhase.RESPONSE, HeaderSetAction("X-Added", "yes")),
        _rule("remove", RulePhase.RESPONSE, HeaderRemoveAction("Content-Length")),
    )))

    request, static = engine.prepare_request(_request())
    assert static is not None and static.status_code == 201
    final = engine.process_response(request, static, request_id=5)

    assert final.headers == {"X-Source": "rule", "X-Added": "yes"}


def test_regex_skips_binary_and_compressed_bodies() -> None:
    rule = _rule("rewrite", RulePhase.RESPONSE, RegexBodyRewriteAction("a", "b"))
    engine = TrafficRuleEngine(TrafficRuleStore((rule,)))
    request = _request()

    binary = ExchangeResponse(200, "OK", {"Content-Type": "application/octet-stream"}, b"a")
    compressed = ExchangeResponse(200, "OK", {"Content-Type": "text/plain", "Content-Encoding": "gzip"}, b"a")

    assert engine.process_response(request, binary, request_id=1) == binary
    assert engine.process_response(request, compressed, request_id=1) == compressed


def test_rule_events_and_serialization_roundtrip() -> None:
    events: list[TrafficRuleApplied] = []
    bus = EventBus()
    bus.subscribe(lambda event: events.append(event) if isinstance(event, TrafficRuleApplied) else None)
    rule = _rule("respond", RulePhase.RESPOND, RespondAction(body=b"body"))
    engine = TrafficRuleEngine(TrafficRuleStore((rule,)), event_bus=bus)

    engine.prepare_request(_request())

    assert events[0].rule_id == "respond"
    assert parse_rule(serialize_rule(rule)) == rule


def test_open_editor_is_a_response_action_and_requests_response_buffering() -> None:
    rule = _rule("editor", RulePhase.RESPONSE, OpenEditorAction())
    engine = TrafficRuleEngine(TrafficRuleStore((rule,)))
    request = _request()
    response = ExchangeResponse(200, "OK", {"Content-Type": "text/plain"}, b"body")

    assert engine.requires_buffered_response(request)
    assert engine.should_open_editor(request, response)
    assert parse_rule(serialize_rule(rule)) == rule

    try:
        _rule("invalid-editor", RulePhase.REQUEST, OpenEditorAction())
    except ValueError as exc:
        assert "response phase" in str(exc)
    else:
        raise AssertionError("Expected OpenEditorAction to require the response phase.")


def test_rule_commands_persist_changes_and_test_regex() -> None:
    persisted: list[tuple[dict[str, object], ...]] = []
    service = TrafficRuleAdministrationService(on_change=persisted.append)

    assert service.execute(["add", "response-rewrite", "rewrite", "GET", "https://api.test/items", "one", "two"]) == "Traffic rule added: rewrite"
    assert service.execute(["test", "rewrite", "one one"]) == "Rule test: 2 match(es): two two"
    assert service.execute(["disable", "rewrite"]) == "Traffic rule disabled: rewrite"
    assert persisted


def test_regex_rule_rejects_unsafe_limits() -> None:
    try:
        RegexBodyRewriteAction("x" * 513, "")
    except ValueError as exc:
        assert "invalid length" in str(exc)
    else:
        raise AssertionError("Expected an invalid regex pattern length.")

    try:
        RegexBodyRewriteAction("x", "", max_matches=1001)
    except ValueError as exc:
        assert "out of range" in str(exc)
    else:
        raise AssertionError("Expected an invalid match limit.")


def test_traffic_rule_config_roundtrip() -> None:
    rule = _rule("respond", RulePhase.RESPOND, RespondAction(body=b"body"))
    document = ConfigDocument(
        settings=RuntimeSettings.create(),
        traffic_rules=(serialize_rule(rule),),
    )

    restored = parse_config_payload(serialize_config_document(document))

    assert parse_rule(restored.traffic_rules[0]) == rule


def test_runtime_schema_accepts_open_editor_only_as_traffic_action() -> None:
    schema = json.loads((Path(__file__).parents[3] / "schemas" / "runtime-config.schema.json").read_text())
    payload = {
        "schema_version": 1,
        "settings": {},
        "traffic_rules": [serialize_rule(_rule("editor", RulePhase.RESPONSE, OpenEditorAction()))],
    }

    assert list(Draft202012Validator(schema).iter_errors(payload)) == []
    assert list(Draft202012Validator(schema).iter_errors({**payload, "policies": []}))
    assert list(Draft202012Validator(schema).iter_errors({**payload, "components": {"traffic_rules": []}}))

    assert parse_config_payload(payload).traffic_rules
    try:
        parse_config_payload({**payload, "components": {"traffic_rules": []}})
    except ConfigValidationError as exc:
        assert "components contains unknown field" in str(exc)
    else:
        raise AssertionError("Expected nested traffic_rules to be rejected.")
