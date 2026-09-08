from dataclasses import replace

import pytest

from proxyscope.contracts.exchanges import ExchangeRequest, ExchangeResponse
from proxyscope.contracts.traffic_rules import (
    HeaderRemoveAction,
    HeaderReplaceAction,
    HeaderSetAction,
    OpenEditorAction,
    RegexBodyRewriteAction,
    RespondAction,
    RulePhase,
    TrafficMatch,
    TrafficRule,
    parse_rule,
    serialize_rule,
)


@pytest.mark.parametrize(
    "action,phase",
    [
        (HeaderSetAction("X-Test", "new"), RulePhase.REQUEST),
        (HeaderReplaceAction("X-Test", "new"), RulePhase.RESPONSE),
        (HeaderRemoveAction("X-Test"), RulePhase.RESPONSE),
        (RespondAction(body=b"\xff\x00"), RulePhase.RESPOND),
        (RegexBodyRewriteAction("a", "b"), RulePhase.REQUEST),
        (OpenEditorAction(), RulePhase.RESPONSE),
    ],
)
def test_every_action_roundtrips_with_full_match(action, phase):
    match = TrafficMatch(("POST",), "http://api.test/items", True, False, "api.test", 201, (("X-Test", "yes"),), "json")
    rule = TrafficRule("r", "Rule", True, 10, phase, match, action)
    assert parse_rule(serialize_rule(rule)) == rule


@pytest.mark.parametrize("field", ["match", "action"])
def test_rule_parser_rejects_non_object_sections(field):
    with pytest.raises(ValueError, match="must be objects"):
        parse_rule({"id": "r", "phase": "response", "action": {"type": "open_editor"}, field: []})


def test_unknown_action_is_rejected():
    with pytest.raises(ValueError, match="Unsupported traffic rule action"):
        parse_rule({"id": "r", "phase": "response", "action": {"type": "unknown"}})


@pytest.mark.parametrize(
    "match,expected",
    [
        (TrafficMatch(), True),
        (TrafficMatch(methods=("post",)), True),
        (TrafficMatch(methods=("GET",)), False),
        (TrafficMatch(host="API.TEST"), True),
        (TrafficMatch(host="other.test"), False),
        (TrafficMatch(url="http://api.test/items"), True),
        (TrafficMatch(url="http://api.test/other"), False),
        (TrafficMatch(url="http://api.test/", url_prefix=True), True),
        (TrafficMatch(url=r"http://api\.test/.*", url_regex=True), True),
        (TrafficMatch(url=r"https://.*", url_regex=True), False),
        (TrafficMatch(headers=(("x-test", "yes"),)), True),
        (TrafficMatch(headers=(("x-test", "no"),)), False),
        (TrafficMatch(headers=(("missing", "yes"),)), False),
        (TrafficMatch(content_type="JSON"), True),
        (TrafficMatch(content_type="text/plain"), False),
    ],
)
def test_match_conditions_independently_select_request_and_response(match, expected):
    headers = {"X-Test": "yes", "Content-Type": "application/json"}
    request = ExchangeRequest("POST", "http://api.test/items", "/items", headers, target_host="api.test")
    response = ExchangeResponse(200, "OK", headers, b"")
    assert match.matches_request(request) is expected
    assert match.matches_response(request, response) is expected


@pytest.mark.parametrize("request_status,expected", [(None, True), (200, True), (404, False)])
def test_response_status_condition(request_status, expected):
    request = ExchangeRequest("GET", "http://api.test/", "/", {})
    assert (
        TrafficMatch(status_code=request_status).matches_response(request, ExchangeResponse(200, "OK", {}, b""))
        is expected
    )


@pytest.mark.parametrize("pattern,replacement,max_matches", [("", "", 1), ("x", "x" * 8193, 1), ("x", "", 0)])
def test_regex_limits_reject_empty_pattern_oversized_replacement_and_zero_matches(pattern, replacement, max_matches):
    with pytest.raises(ValueError):
        RegexBodyRewriteAction(pattern, replacement, max_matches=max_matches)


@pytest.mark.parametrize(
    "changes", [{"rule_id": ""}, {"name": " "}, {"phase": RulePhase.REQUEST}, {"action": OpenEditorAction()}]
)
def test_rules_reject_invalid_identity_and_phase_action_combinations(changes):
    rule = TrafficRule("r", "Rule", True, 0, RulePhase.RESPOND, TrafficMatch(), RespondAction())
    with pytest.raises(ValueError):
        replace(rule, **changes)
