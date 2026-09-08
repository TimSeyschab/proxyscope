from dataclasses import replace

import pytest

from proxyscope.application.traffic_rules import TrafficRuleAdministrationService
from proxyscope.contracts.traffic_rules import (
    HeaderRemoveAction,
    HeaderReplaceAction,
    HeaderSetAction,
    RespondAction,
    RulePhase,
    TrafficMatch,
    TrafficRule,
)


def test_administration_crud_and_missing_ids():
    service = TrafficRuleAdministrationService()
    rule = TrafficRule("one", "One", True, 0, RulePhase.RESPOND, TrafficMatch(), RespondAction())
    assert service.execute([]) == "Rules: none"
    assert service.get_rule("one") is None
    assert not service.replace_rule(rule)
    assert not service.remove_rule("one")
    service.add_rule(rule)
    assert service.execute(["list"]) == "Rules: one (respond)"
    assert service.replace_rule(replace(rule, name="Updated"))
    assert service.get_rule("one").name == "Updated"
    assert service.remove_rule("one")
    assert service.list_rules() == ()


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["enable", "missing"], "Traffic rule not found: missing"),
        (["remove", "missing"], "Traffic rule not found: missing"),
        (["test", "missing", "sample"], "Traffic rule not found: missing"),
        (["unknown"], "Usage: rule"),
        (["add", "respond", "r", "GET", "http://api.test", "invalid"], "Traffic rule not added:"),
        (["add", "response-rewrite", "r", "GET", "http://api.test", "", "x"], "Traffic rule not added:"),
        (
            ["add", "request-header", "r", "GET", "http://api.test", "unknown", "X-Test", "value"],
            "Header operation must",
        ),
    ],
)
def test_invalid_commands_do_not_add_rules(arguments, message):
    service = TrafficRuleAdministrationService()
    assert service.execute(arguments).startswith(message)
    assert service.list_rules() == ()


@pytest.mark.parametrize("phase", ["request", "response"])
@pytest.mark.parametrize(
    "operation,action", [("set", HeaderSetAction), ("replace", HeaderReplaceAction), ("remove", HeaderRemoveAction)]
)
def test_header_commands_create_correct_action_and_reject_duplicate(phase, operation, action):
    service = TrafficRuleAdministrationService()
    arguments = ["add", f"{phase}-header", "r", "GET", "http://api.test", operation, "X-Test", "value"]
    assert service.execute(arguments) == "Traffic rule added: r"
    rule = service.get_rule("r")
    assert rule.phase is RulePhase(phase)
    assert isinstance(rule.action, action)
    assert rule.action.name == "X-Test"
    assert service.execute(arguments).startswith("Traffic rule not added: Traffic rule already exists")
    assert service.list_rules() == (rule,)


def test_non_regex_rule_cannot_be_tested_and_enable_restores_rule():
    service = TrafficRuleAdministrationService()
    service.execute(["add", "respond", "r", "GET", "http://api.test", "201", "body"])
    assert service.execute(["test", "r", "body"]) == "Traffic rule test supports body rewrite rules only."
    service.execute(["disable", "r"])
    assert service.execute(["list"]) == "Rules: none"
    assert service.execute(["enable", "r"]) == "Traffic rule enabled: r"
    assert service.get_rule("r").enabled
