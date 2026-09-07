from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace

from proxyscope.application.events import EventBus
from proxyscope.contracts.events import RuntimeEvent
from proxyscope.contracts.ports import ComponentEventBus
from proxyscope.contracts.traffic_rules import (
    HeaderRemoveAction,
    HeaderReplaceAction,
    HeaderSetAction,
    RegexBodyRewriteAction,
    RespondAction,
    RulePhase,
    TrafficAction,
    TrafficMatch,
    TrafficRule,
    parse_rule,
    serialize_rule,
)
from proxyscope.contracts.traffic_rules.events import TrafficRulesResult, TrafficRulesUpdateRequested
from proxyscope.contracts.traffic_rules.models import (
    MAX_PATTERN_LENGTH,
    MAX_REGEX_MATCHES,
    MAX_REPLACEMENT_LENGTH,
)

from .engine import TrafficRuleEngine
from .events import TrafficRuleEventHandler
from .store import TrafficRuleStore


class TrafficRuleAdministrationService:
    def __init__(
        self,
        store: TrafficRuleStore | None = None,
        *,
        on_change: Callable[[tuple[dict[str, object], ...]], None] | None = None,
        event_bus: ComponentEventBus | None = None,
    ) -> None:
        self.store = store or TrafficRuleStore()
        self._event_bus = event_bus or EventBus()
        self._event_bus.subscribe(TrafficRuleEventHandler(self.store, self._event_bus, on_change=on_change))

    def replace_rules(self, rules: tuple[TrafficRule, ...]) -> None:
        self._update(TrafficRulesUpdateRequested(operation="replace_all", rules=rules))

    def list_rules(self) -> tuple[TrafficRule, ...]:
        return self.store.snapshot()

    def get_rule(self, rule_id: str) -> TrafficRule | None:
        return self.store.get(rule_id)

    def add_rule(self, rule: TrafficRule) -> None:
        self._update(TrafficRulesUpdateRequested(operation="add", rules=(rule,)))

    def replace_rule(self, rule: TrafficRule) -> bool:
        if self.store.get(rule.rule_id) is None:
            return False
        self._update(TrafficRulesUpdateRequested(operation="replace", rules=(rule,)))
        return True

    def remove_rule(self, rule_id: str) -> bool:
        if self.store.get(rule_id) is None:
            return False
        self._update(TrafficRulesUpdateRequested(operation="remove", rule_ids=(rule_id,)))
        return True

    def execute(self, arguments: list[str]) -> str:
        try:
            return self._execute(arguments)
        except ValueError as exc:
            return str(exc)

    def _execute(self, arguments: list[str]) -> str:
        if not arguments or arguments == ["list"]:
            rules = self.store.list()
            return "Rules: " + (", ".join(f"{rule.rule_id} ({rule.phase.value})" for rule in rules) or "none")
        if len(arguments) == 2 and arguments[0] in {"enable", "disable"}:
            rule = self.store.get(arguments[1])
            if rule is None:
                return f"Traffic rule not found: {arguments[1]}"
            self._update(
                TrafficRulesUpdateRequested(
                    operation="replace", rules=(replace(rule, enabled=arguments[0] == "enable"),)
                )
            )
            return f"Traffic rule {arguments[0]}d: {rule.rule_id}"
        if len(arguments) == 2 and arguments[0] == "remove":
            self._update(TrafficRulesUpdateRequested(operation="remove", rule_ids=(arguments[1],)))
            return f"Traffic rule removed: {arguments[1]}"
        if len(arguments) >= 2 and arguments[0] == "test":
            return self._test(arguments[1], " ".join(arguments[2:]))
        if len(arguments) >= 6 and arguments[:2] == ["add", "respond"]:
            return self._add_respond(arguments)
        if len(arguments) >= 7 and arguments[:2] in (["add", "request-rewrite"], ["add", "response-rewrite"]):
            return self._add_rewrite(arguments)
        if len(arguments) >= 8 and arguments[:2] in (["add", "request-header"], ["add", "response-header"]):
            return self._add_header(arguments)
        return "Usage: rule <list|enable|disable|remove|test|add> ..."

    def _add_respond(self, arguments: list[str]) -> str:
        _, _, rule_id, method, url, raw_status, *body = arguments
        try:
            rule = TrafficRule(
                rule_id,
                rule_id,
                True,
                0,
                RulePhase.RESPOND,
                TrafficMatch(methods=(method,), url=url),
                RespondAction(int(raw_status), body=" ".join(body).encode("utf-8")),
            )
            self._update(TrafficRulesUpdateRequested(operation="add", rules=(rule,)))
        except ValueError as exc:
            return f"Traffic rule not added: {exc}"
        return f"Traffic rule added: {rule_id}"

    def _add_rewrite(self, arguments: list[str]) -> str:
        _, kind, rule_id, method, url, pattern, replacement, *_ = arguments
        phase = RulePhase.REQUEST if kind == "request-rewrite" else RulePhase.RESPONSE
        try:
            rule = TrafficRule(
                rule_id,
                rule_id,
                True,
                0,
                phase,
                TrafficMatch(methods=(method,), url=url),
                RegexBodyRewriteAction(pattern, replacement),
            )
            self._update(TrafficRulesUpdateRequested(operation="add", rules=(rule,)))
        except ValueError as exc:
            return f"Traffic rule not added: {exc}"
        return f"Traffic rule added: {rule_id}"

    def _add_header(self, arguments: list[str]) -> str:
        _, kind, rule_id, method, url, operation, name, *value = arguments
        action: TrafficAction
        if operation == "set":
            action = HeaderSetAction(name, " ".join(value))
        elif operation == "replace":
            action = HeaderReplaceAction(name, " ".join(value))
        elif operation == "remove":
            action = HeaderRemoveAction(name)
        else:
            return "Header operation must be set, replace, or remove."
        phase = RulePhase.REQUEST if kind == "request-header" else RulePhase.RESPONSE
        try:
            self._update(
                TrafficRulesUpdateRequested(
                    operation="add",
                    rules=(
                        TrafficRule(rule_id, rule_id, True, 0, phase, TrafficMatch(methods=(method,), url=url), action),
                    ),
                )
            )
        except ValueError as exc:
            return f"Traffic rule not added: {exc}"
        return f"Traffic rule added: {rule_id}"

    def _test(self, rule_id: str, sample: str) -> str:
        rule = self.store.get(rule_id)
        if rule is None:
            return f"Traffic rule not found: {rule_id}"
        if not isinstance(rule.action, RegexBodyRewriteAction):
            return "Traffic rule test supports body rewrite rules only."
        result, count = re.subn(
            rule.action.pattern, rule.action.replacement, sample, count=rule.action.max_matches, flags=rule.action.flags
        )
        return f"Rule test: {count} match(es): {result}"

    def _update(self, request: TrafficRulesUpdateRequested) -> None:
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




__all__ = [
    "HeaderRemoveAction",
    "HeaderReplaceAction",
    "HeaderSetAction",
    "MAX_PATTERN_LENGTH",
    "MAX_REGEX_MATCHES",
    "MAX_REPLACEMENT_LENGTH",
    "RegexBodyRewriteAction",
    "RespondAction",
    "RulePhase",
    "TrafficAction",
    "TrafficMatch",
    "TrafficRule",
    "TrafficRuleEngine",
    "TrafficRuleStore",
    "parse_rule",
    "serialize_rule",
    "TrafficRuleAdministrationService",
]
