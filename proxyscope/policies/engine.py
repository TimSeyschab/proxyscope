from dataclasses import dataclass

from proxyscope.policies.matching import (
    normalize_http_method,
    policy_rule_matches_request,
    policy_sort_key,
    request_url_candidates,
)
from proxyscope.policies.models import OpenEditorAction, PolicyAction, PolicyRule, StaticResponseAction
from proxyscope.policies.repository import PolicyRepository


@dataclass(frozen=True)
class PolicyEvaluation:
    rule: PolicyRule | None = None

    @property
    def action(self) -> PolicyAction | None:
        return self.rule.action if self.rule is not None else None


class PolicyEngine:
    def __init__(self, repository: PolicyRepository) -> None:
        self._repository = repository

    def evaluate(self, *, method: str, url: str) -> PolicyEvaluation:
        normalized_method = normalize_http_method(method)
        candidates = request_url_candidates(url)
        for rule in sorted(self._repository.list(), key=policy_sort_key, reverse=True):
            if rule.enabled and policy_rule_matches_request(
                rule=rule,
                method=normalized_method,
                url_candidates=candidates,
            ):
                return PolicyEvaluation(rule)
        return PolicyEvaluation()

    def should_modify_response_for_request(self, *, method: str, url: str) -> bool:
        return isinstance(self.evaluate(method=method, url=url).action, OpenEditorAction)

    def get_static_response_template_for_request(self, *, method: str, url: str) -> StaticResponseAction | None:
        action = self.evaluate(method=method, url=url).action
        return action if isinstance(action, StaticResponseAction) else None
