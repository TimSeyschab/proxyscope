from collections.abc import Callable, Iterable
from threading import RLock

from proxyscope.contracts.traffic_rules import TrafficRule
from proxyscope.contracts.traffic_rules.events import TrafficRuleScope, TrafficRulesUpdateRequested


class TrafficRuleStore:
    def __init__(self, rules: Iterable[TrafficRule] = ()) -> None:
        self._rules: dict[str, TrafficRule] = {}
        self._scopes: dict[str, TrafficRuleScope] = {}
        self._lock = RLock()
        for rule in rules:
            self.add(rule)

    def add(self, rule: TrafficRule) -> None:
        with self._lock:
            if rule.rule_id in self._rules:
                raise ValueError(f"Traffic rule already exists: {rule.rule_id}")
            self._rules[rule.rule_id] = rule

    def replace(self, rule: TrafficRule) -> bool:
        with self._lock:
            if rule.rule_id not in self._rules:
                return False
            self._rules[rule.rule_id] = rule
            return True

    def remove(self, rule_id: str) -> bool:
        with self._lock:
            return self._rules.pop(rule_id, None) is not None

    def get(self, rule_id: str) -> TrafficRule | None:
        with self._lock:
            return self._rules.get(rule_id)

    def replace_all(self, rules: Iterable[TrafficRule]) -> None:
        replacement = TrafficRuleStore(rules)
        with self._lock:
            self._rules = replacement._rules

    def set_scope(self, scope: TrafficRuleScope) -> None:
        with self._lock:
            self._scopes[scope.owner_id] = scope

    def snapshot(self) -> tuple[TrafficRule, ...]:
        with self._lock:
            return tuple(sorted(self._rules.values(), key=lambda item: (-item.priority, item.rule_id)))

    def list(self, *, scoped: bool = False) -> tuple[TrafficRule, ...]:
        with self._lock:
            owned = {rule_id for scope in self._scopes.values() for rule_id in scope.rule_ids}
            active = {rule_id for scope in self._scopes.values() for rule_id in scope.active_rule_ids}
            return tuple(
                rule
                for rule in self.snapshot()
                if rule.enabled and (not scoped or rule.rule_id not in owned or rule.rule_id in active)
            )

    def apply_update(
        self,
        request: TrafficRulesUpdateRequested,
        *,
        before_commit: Callable[[tuple[TrafficRule, ...]], None] | None = None,
    ) -> None:
        with self._lock:
            replacement = TrafficRuleStore(self.snapshot())
            if request.operation == "replace_all":
                if request.rule_ids:
                    raise ValueError("Replace-all requests require rules, not rule IDs.")
                replacement.replace_all(request.rules)
            elif request.operation in {"add", "replace"}:
                if request.rule_ids:
                    raise ValueError("Add and replace requests require rules, not rule IDs.")
                if len({rule.rule_id for rule in request.rules}) != len(request.rules):
                    raise ValueError("Duplicate rule IDs in update.")
                for rule in request.rules:
                    if request.operation == "add":
                        replacement.add(rule)
                    elif not replacement.replace(rule):
                        raise ValueError(f"Traffic rule not found: {rule.rule_id}")
            elif request.operation == "remove":
                if request.rules:
                    raise ValueError("Remove requests require rule IDs, not rules.")
                for rule_id in request.rule_ids:
                    if not replacement.remove(rule_id):
                        raise ValueError(f"Traffic rule not found: {rule_id}")
            else:
                raise ValueError(f"Unsupported traffic rule operation: {request.operation}")
            if before_commit is not None:
                before_commit(replacement.snapshot())
            self._rules = replacement._rules
            if request.scope is not None:
                self.set_scope(request.scope)
