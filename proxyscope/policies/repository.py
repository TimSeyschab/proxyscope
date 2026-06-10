from collections.abc import Iterable
from threading import RLock
from typing import Protocol, runtime_checkable

from proxyscope.policies.models import PolicyRule


@runtime_checkable
class PolicyRepository(Protocol):
    def list(self) -> tuple[PolicyRule, ...]: ...

    def replace_all(self, rules: Iterable[PolicyRule]) -> None: ...

    def add(self, rule: PolicyRule) -> None: ...

    def get(self, name: str) -> PolicyRule | None: ...

    def replace(self, name: str, replacement: PolicyRule) -> bool: ...

    def remove(self, name: str) -> bool: ...


class InMemoryPolicyRepository:
    def __init__(self, rules: Iterable[PolicyRule] = ()) -> None:
        self._lock = RLock()
        self._rules = list(rules)

    def list(self) -> tuple[PolicyRule, ...]:
        with self._lock:
            return tuple(self._rules)

    def replace_all(self, rules: Iterable[PolicyRule]) -> None:
        with self._lock:
            self._rules = list(rules)

    def add(self, rule: PolicyRule) -> None:
        with self._lock:
            self._rules.append(rule)

    def get(self, name: str) -> PolicyRule | None:
        with self._lock:
            return next((rule for rule in self._rules if rule.name == name), None)

    def replace(self, name: str, replacement: PolicyRule) -> bool:
        with self._lock:
            for index, rule in enumerate(self._rules):
                if rule.name == name:
                    self._rules[index] = replacement
                    return True
        return False

    def remove(self, name: str) -> bool:
        with self._lock:
            kept = [rule for rule in self._rules if rule.name != name]
            removed = len(kept) != len(self._rules)
            self._rules = kept
            return removed
