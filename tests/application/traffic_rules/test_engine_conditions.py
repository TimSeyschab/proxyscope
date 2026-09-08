import pytest

from proxyscope.application.traffic_rules import TrafficRuleEngine, TrafficRuleStore
from proxyscope.contracts.exchanges import ExchangeRequest, ExchangeResponse
from proxyscope.contracts.traffic_rules import (
    HeaderRemoveAction,
    HeaderReplaceAction,
    HeaderSetAction,
    RegexBodyRewriteAction,
    RulePhase,
    TrafficMatch,
    TrafficRule,
)


@pytest.mark.parametrize("phase", [RulePhase.REQUEST, RulePhase.RESPONSE])
@pytest.mark.parametrize(
    "action,headers,expected",
    [
        (HeaderSetAction("X-Test", "new"), {"x-test": "old"}, {"x-test": "old"}),
        (HeaderReplaceAction("X-Test", "new"), {}, {}),
        (HeaderRemoveAction("X-Test"), {}, {}),
        (HeaderReplaceAction("X-Test", "new"), {"x-test": "old"}, {"X-Test": "new"}),
        (HeaderRemoveAction("X-Test"), {"x-test": "old"}, {}),
    ],
)
def test_header_actions_distinguish_absent_and_present_headers(phase, action, headers, expected):
    rule = TrafficRule("r", "Rule", True, 0, phase, TrafficMatch(), action)
    engine = TrafficRuleEngine(TrafficRuleStore([rule]))
    request = ExchangeRequest("GET", "http://api.test/", "/", headers)
    if phase is RulePhase.REQUEST:
        result, _ = engine.prepare_request(request)
    else:
        result = engine.process_response(request, ExchangeResponse(200, "OK", headers, b""), request_id=1)
    assert result.headers == expected


@pytest.mark.parametrize("phase", [RulePhase.REQUEST, RulePhase.RESPONSE])
@pytest.mark.parametrize(
    "headers,body",
    [
        ({"Content-Type": "text/plain"}, b"\xff"),
        ({"Content-Type": "text/plain"}, b"no match"),
        ({"Content-Type": "application/octet-stream"}, b"original"),
        ({"Content-Type": "text/plain", "Content-Encoding": "gzip"}, b"original"),
    ],
)
def test_ineligible_body_rewrites_preserve_original_exchange(phase, headers, body):
    rule = TrafficRule("r", "Rule", True, 0, phase, TrafficMatch(), RegexBodyRewriteAction("original", "edited"))
    engine = TrafficRuleEngine(TrafficRuleStore([rule]))
    request = ExchangeRequest("GET", "http://api.test/", "/", headers, body)
    response = ExchangeResponse(200, "OK", headers, body)
    if phase is RulePhase.REQUEST:
        result, _ = engine.prepare_request(request)
        assert result is request
    else:
        assert engine.process_response(request, response, request_id=1) is response


@pytest.mark.parametrize("phase", [RulePhase.REQUEST, RulePhase.RESPONSE])
def test_nonmatching_rule_leaves_headers_unchanged(phase):
    rule = TrafficRule("r", "Rule", True, 0, phase, TrafficMatch(methods=("POST",)), HeaderSetAction("X-Test", "new"))
    engine = TrafficRuleEngine(TrafficRuleStore([rule]))
    request = ExchangeRequest("GET", "http://api.test/", "/", {})
    if phase is RulePhase.REQUEST:
        assert engine.prepare_request(request)[0] is request
    else:
        response = ExchangeResponse(200, "OK", {}, b"")
        assert engine.process_response(request, response, request_id=1) is response
