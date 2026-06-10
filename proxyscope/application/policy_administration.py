from collections.abc import Iterable
from dataclasses import replace

from proxyscope.policies.matching import (
    first_rule_method,
    normalize_http_method,
    normalize_policy_url,
    policy_description,
    policy_sort_key,
    rule_matches_url,
    rule_method_display,
    rule_url_display,
)
from proxyscope.policies.models import OpenEditorAction, PolicyRule, RequestMatchRule, StaticResponseAction
from proxyscope.policies.repository import InMemoryPolicyRepository, PolicyRepository


class PolicyAdministrationService:
    def __init__(
        self,
        *,
        rules: Iterable[PolicyRule] = (),
        repository: PolicyRepository | None = None,
    ) -> None:
        resolved_rules = tuple(rules)
        if repository is not None and resolved_rules:
            raise ValueError("Provide either rules or repository, not both.")
        self._repository = repository or InMemoryPolicyRepository(resolved_rules)

    @property
    def repository(self) -> PolicyRepository:
        return self._repository

    def list_rules(self) -> tuple[PolicyRule, ...]:
        return self._repository.list()

    def sorted_rules(self) -> tuple[PolicyRule, ...]:
        return tuple(sorted(self.list_rules(), key=policy_sort_key, reverse=True))

    def replace_all(self, rules: Iterable[PolicyRule]) -> None:
        self._repository.replace_all(rules)

    def add_rule(self, rule: PolicyRule) -> None:
        self._repository.add(rule)

    def clear_rules(self) -> None:
        self.replace_all(())

    def descriptions(self) -> tuple[str, ...]:
        return tuple(policy_description(rule) for rule in self.sorted_rules())

    def remove_rule(self, name: str) -> bool:
        normalized = _normalize_name(name)
        removed = self._repository.remove(normalized)
        return removed

    def get_rule(self, name: str) -> PolicyRule | None:
        return self._repository.get(_normalize_name(name))

    def replace_rule(self, name: str, replacement: PolicyRule) -> bool:
        replaced = self._repository.replace(_normalize_name(name), replacement)
        return replaced

    def set_enabled(self, name: str, *, enabled: bool) -> bool:
        normalized = _normalize_name(name)
        rule = self._repository.get(normalized)
        changed = rule is not None and self._repository.replace(normalized, replace(rule, enabled=enabled))
        return changed

    def set_priority(self, name: str, *, priority: int) -> bool:
        normalized = _normalize_name(name)
        rule = self._repository.get(normalized)
        changed = rule is not None and self._repository.replace(normalized, replace(rule, priority=priority))
        return changed

    def add_static_response(
        self,
        *,
        url: str,
        status_code: int = 200,
        reason: str = "OK",
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        method: str | None = None,
        url_prefix: bool = False,
        name: str | None = None,
        priority: int = 0,
    ) -> str:
        normalized_url = normalize_policy_url(url)
        normalized_method = normalize_http_method(method) if method is not None else None
        rule_name = name or f"static-response-{len(self.list_rules()) + 1}"
        self.add_rule(
            PolicyRule(
                name=rule_name,
                enabled=True,
                priority=priority,
                action=StaticResponseAction(
                    status_code=status_code,
                    reason=reason,
                    headers=dict(headers or {}),
                    body=body,
                ),
                match=RequestMatchRule(
                    methods=(normalized_method,) if normalized_method is not None else None,
                    url_prefix=normalized_url if url_prefix else None,
                    url_exact=None if url_prefix else normalized_url,
                ),
            )
        )
        return rule_name

    def open_editor_entries(self) -> tuple[str, ...]:
        rules = [rule for rule in self.list_rules() if isinstance(rule.action, OpenEditorAction) and rule.enabled]
        return tuple(f"{rule_method_display(rule)} {rule_url_display(rule)}" for rule in rules)

    def add_open_editor(
        self,
        value: str,
        *,
        method: str = "GET",
        url_prefix: bool = False,
        priority: int = 0,
    ) -> str:
        normalized_url = normalize_policy_url(value)
        normalized_method = normalize_http_method(method)
        self.add_rule(
            PolicyRule(
                name=f"open-editor-{len(self.list_rules()) + 1}",
                enabled=True,
                priority=priority,
                action=OpenEditorAction(),
                match=RequestMatchRule(
                    methods=(normalized_method,),
                    url_exact=None if url_prefix else normalized_url,
                    url_prefix=normalized_url if url_prefix else None,
                ),
            )
        )
        return f"{normalized_method} {normalized_url}"

    def remove_open_editor(self, value: str, *, method: str | None = None) -> bool:
        normalized_url = normalize_policy_url(value)
        normalized_method = normalize_http_method(method) if method is not None else None
        removed = False
        kept: list[PolicyRule] = []
        for rule in self.list_rules():
            matches = (
                isinstance(rule.action, OpenEditorAction)
                and rule_matches_url(rule, normalized_url)
                and (normalized_method is None or first_rule_method(rule) == normalized_method)
            )
            if matches:
                removed = True
            else:
                kept.append(rule)
        if removed:
            self.replace_all(kept)
        return removed

    def clear_open_editor(self) -> None:
        self.replace_all(rule for rule in self.list_rules() if not isinstance(rule.action, OpenEditorAction))


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("Policy name must not be empty.")
    return normalized
