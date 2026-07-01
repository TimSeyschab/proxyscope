import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.journal import RequestJournal
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.application.services import RuntimeApplicationServices
from proxyscope.config.repository import ConfigRepository, JsonConfigRepository
from proxyscope.config.settings import ConfigDocument, RuntimeSettings, normalize_whitelist_entry
from proxyscope.policies.models import PolicyRule
from proxyscope.policies.repository import PolicyRepository

__all__ = [
    "RuntimeTestContext",
    "normalize_whitelist_entry",
    "processing_dependencies",
    "runtime_application_services",
    "runtime_dependencies",
]


@dataclass(frozen=True)
class RuntimeSnapshot:
    settings: RuntimeSettings
    policies: tuple[PolicyRule, ...]
    config_path: Path | None


class RuntimeTestContext:
    """Test-only composition helper for explicit runtime dependencies."""

    def __init__(
        self,
        *,
        log_level: int = logging.INFO,
        log_whitelist: Iterable[str] | None = None,
        cache_invalidation_enabled: bool = True,
        mitm_enabled: bool = True,
        mitm_certs_dir: str | Path = "certs",
        config_path: str | Path | None = None,
        policy_rules: Iterable[PolicyRule] | None = None,
        policy_repository: PolicyRepository | None = None,
        config_repository: ConfigRepository | None = None,
        settings: RuntimeSettings | None = None,
    ) -> None:
        if policy_repository is not None and policy_rules is not None:
            raise ValueError("Provide either policy_rules or policy_repository, not both.")
        self.settings_state = RuntimeSettingsState(
            settings=settings,
            log_level=log_level,
            log_whitelist=log_whitelist or (),
            cache_invalidation_enabled=cache_invalidation_enabled,
            mitm_enabled=mitm_enabled,
            mitm_certs_dir=mitm_certs_dir,
        )
        self.policy_administration = PolicyAdministrationService(
            rules=policy_rules or (),
            repository=policy_repository,
        )
        self.configuration = RuntimeConfigurationService(
            settings=self.settings_state,
            policies=self.policy_administration,
            repository=config_repository or JsonConfigRepository(),
            path=config_path,
        )

    @property
    def config_path(self) -> Path | None:
        return self.configuration.path

    @property
    def config_repository(self) -> ConfigRepository:
        return self.configuration.repository

    @property
    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            settings=self.settings_state.snapshot,
            policies=self.policy_administration.list_rules(),
            config_path=self.configuration.path,
        )

    @property
    def settings(self) -> RuntimeSettings:
        return self.settings_state.snapshot

    @property
    def log_level(self) -> int:
        return self.settings_state.log_level

    def log_level_name(self) -> str:
        return self.settings_state.log_level_name()

    def set_log_level(self, value: str | int) -> int:
        return self.settings_state.set_log_level(value)

    def whitelist_entries(self) -> tuple[str, ...]:
        return self.settings_state.whitelist_entries()

    def add_whitelist_entry(self, value: str) -> str:
        return self.settings_state.add_whitelist_entry(value)

    def remove_whitelist_entry(self, value: str) -> bool:
        return self.settings_state.remove_whitelist_entry(value)

    def clear_whitelist(self) -> None:
        self.settings_state.clear_whitelist()

    def should_log_for_host(self, host: str | None) -> bool:
        return self.settings_state.should_log_for_host(host)

    @property
    def cache_invalidation_enabled(self) -> bool:
        return self.settings_state.cache_invalidation_enabled

    def set_cache_invalidation_enabled(self, enabled: bool) -> bool:
        return self.settings_state.set_cache_invalidation_enabled(enabled)

    def toggle_cache_invalidation(self) -> bool:
        return self.settings_state.toggle_cache_invalidation()

    @property
    def mitm_enabled(self) -> bool:
        return self.settings_state.mitm_enabled

    def set_mitm_enabled(self, enabled: bool) -> bool:
        return self.settings_state.set_mitm_enabled(enabled)

    @property
    def mitm_certs_dir(self) -> Path:
        return self.settings_state.mitm_certs_dir

    def set_mitm_certs_dir(self, value: str | Path) -> Path:
        return self.settings_state.set_mitm_certs_dir(value)

    @property
    def policy_repository(self) -> PolicyRepository:
        return self.policy_administration.repository

    def policy_rules(self) -> tuple[PolicyRule, ...]:
        return self.policy_administration.list_rules()

    def sorted_policy_rules(self) -> tuple[PolicyRule, ...]:
        return self.policy_administration.sorted_rules()

    def set_policy_rules(self, rules: Iterable[PolicyRule]) -> None:
        self.policy_administration.replace_all(rules)

    def add_policy_rule(self, rule: PolicyRule) -> None:
        self.policy_administration.add_rule(rule)

    def clear_policy_rules(self) -> None:
        self.policy_administration.clear_rules()

    def policy_descriptions(self) -> tuple[str, ...]:
        return self.policy_administration.descriptions()

    def remove_policy_rule(self, name: str) -> bool:
        return self.policy_administration.remove_rule(name)

    def get_policy_rule(self, name: str) -> PolicyRule | None:
        return self.policy_administration.get_rule(name)

    def replace_policy_rule(self, name: str, replacement: PolicyRule) -> bool:
        return self.policy_administration.replace_rule(name, replacement)

    def set_policy_rule_enabled(self, name: str, *, enabled: bool) -> bool:
        return self.policy_administration.set_enabled(name, enabled=enabled)

    def set_policy_rule_priority(self, name: str, *, priority: int) -> bool:
        return self.policy_administration.set_priority(name, priority=priority)

    def add_static_response_rule(
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
        return self.policy_administration.add_static_response(
            url=url,
            status_code=status_code,
            reason=reason,
            headers=headers,
            body=body,
            method=method,
            url_prefix=url_prefix,
            name=name,
            priority=priority,
        )

    def modification_whitelist_entries(self) -> tuple[str, ...]:
        return self.policy_administration.open_editor_entries()

    def open_editor_policy_entries(self) -> tuple[str, ...]:
        return self.policy_administration.open_editor_entries()

    def add_open_editor_policy(
        self,
        value: str,
        *,
        method: str = "GET",
        url_prefix: bool = False,
        priority: int = 0,
    ) -> str:
        return self.policy_administration.add_open_editor(
            value,
            method=method,
            url_prefix=url_prefix,
            priority=priority,
        )

    def remove_open_editor_policy(self, value: str, *, method: str | None = None) -> bool:
        return self.policy_administration.remove_open_editor(value, method=method)

    def clear_open_editor_policies(self) -> None:
        self.policy_administration.clear_open_editor()

    def add_modification_whitelist_entry(
        self,
        value: str,
        *,
        method: str = "GET",
        url_prefix: bool = False,
        priority: int = 0,
    ) -> str:
        return self.add_open_editor_policy(value, method=method, url_prefix=url_prefix, priority=priority)

    def remove_modification_whitelist_entry(self, value: str, *, method: str | None = None) -> bool:
        return self.remove_open_editor_policy(value, method=method)

    def clear_modification_whitelist(self) -> None:
        self.clear_open_editor_policies()

    def attach_config_path(self, path: str | Path) -> None:
        self.configuration.attach(path)

    def to_config_document(self) -> ConfigDocument:
        return self.configuration.create_document()

    def apply_config_document(self, document: ConfigDocument) -> None:
        self.configuration.apply_document(document)

    def save_to_path(self, path: str | Path) -> Path:
        saved = self.configuration.save(path)
        assert saved is not None
        return saved

    def save(self) -> None:
        self.configuration.save()

    @classmethod
    def load_from_file(
        cls,
        path: str | Path,
        *,
        config_repository: ConfigRepository | None = None,
    ) -> "RuntimeTestContext":
        resolved_path = Path(path)
        repository = config_repository or JsonConfigRepository()
        document = repository.load(resolved_path)
        return cls(
            config_path=resolved_path,
            config_repository=repository,
            settings=document.settings,
            policy_rules=document.policies,
        )


def runtime_dependencies(config: RuntimeTestContext) -> dict[str, object]:
    return {
        "settings": config.settings_state,
        "policies": config.policy_administration,
        "configuration": config.configuration,
    }


def runtime_application_services(
    config: RuntimeTestContext,
    *,
    request_journal: RequestJournal | None = None,
    response_modifier: ResponseModifierService | None = None,
    proxy_base_url: str | None = None,
) -> RuntimeApplicationServices:
    from proxyscope.adapters.factory import create_default_runtime_application_services

    return create_default_runtime_application_services(
        **runtime_dependencies(config),
        request_journal=request_journal or RequestJournal(),
        response_modifier=response_modifier or ResponseModifierService(),
        proxy_base_url=proxy_base_url,
    )


def processing_dependencies(config: RuntimeTestContext) -> dict[str, object]:
    return {
        "settings": config.settings_state,
        "policies": config.policy_administration,
    }
