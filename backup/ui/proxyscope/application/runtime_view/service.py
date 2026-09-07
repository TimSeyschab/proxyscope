from dataclasses import dataclass
from pathlib import Path

from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.policies.models import PolicyRule, StaticResponseAction
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.requests import RequestApplicationService
from proxyscope.application.runtime_settings import RuntimeSettingsState


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    log_level_name: str
    whitelist_entries: tuple[str, ...]
    cache_invalidation_enabled: bool
    mitm_enabled: bool
    editor_policy_count: int
    policy_count: int
    request_filter_summary: str
    config_path: Path | None


@dataclass(frozen=True)
class RuntimePolicyListItem:
    name: str
    description: str


class RuntimeViewApplicationService:
    def __init__(
        self,
        *,
        settings: RuntimeSettingsState,
        policies: PolicyAdministrationService,
        configuration: RuntimeConfigurationService,
        requests: RequestApplicationService,
    ) -> None:
        self._settings = settings
        self._policies = policies
        self._configuration = configuration
        self._requests = requests

    def status(self) -> RuntimeStatusSnapshot:
        settings_snapshot = self._settings.snapshot
        return RuntimeStatusSnapshot(
            log_level_name=self._settings.log_level_name(),
            whitelist_entries=settings_snapshot.log_whitelist,
            cache_invalidation_enabled=settings_snapshot.cache_invalidation_enabled,
            mitm_enabled=settings_snapshot.mitm_enabled,
            editor_policy_count=len(self._policies.open_editor_entries()),
            policy_count=len(self._policies.list_rules()),
            request_filter_summary=self._requests.filter_summary,
            config_path=self._configuration.path,
        )

    def policy_items(self) -> list[RuntimePolicyListItem]:
        return [
            RuntimePolicyListItem(name=rule.name, description=_format_policy_item(rule))
            for rule in self._policies.sorted_rules()
        ]


def _format_policy_item(rule: PolicyRule) -> str:
    state = "ON" if rule.enabled else "OFF"
    method = ",".join(rule.match.methods or ("*",))
    target = rule.match.url_exact or rule.match.url_prefix or "*"
    if isinstance(rule.action, StaticResponseAction):
        return f"{state:>3} p={rule.priority} {rule.name} | static {method} {target} -> {rule.action.status_code}"
    return f"{state:>3} p={rule.priority} {rule.name} | open_editor {method} {target}"
