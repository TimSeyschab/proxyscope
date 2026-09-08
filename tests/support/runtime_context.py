import logging
from collections.abc import Iterable
from pathlib import Path

from proxyscope.application.configuration import (
    ConfigDocument,
    ConfigRepository,
    JsonConfigRepository,
    RuntimeConfigurationService,
    RuntimeSettings,
    normalize_whitelist_entry,
)
from proxyscope.application.journal import RequestJournal
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.application.services import RuntimeApplicationServices
from proxyscope.application.traffic_rules import TrafficRuleAdministrationService, TrafficRuleEngine, TrafficRuleStore
from proxyscope.contracts.traffic_rules import OpenEditorAction, RespondAction, RulePhase, TrafficMatch, TrafficRule

__all__ = [
    "RuntimeTestContext",
    "normalize_whitelist_entry",
    "processing_dependencies",
    "runtime_application_services",
    "runtime_dependencies",
]


class RuntimeTestContext:
    def __init__(
        self,
        *,
        log_level: int = logging.INFO,
        log_whitelist: Iterable[str] | None = None,
        cache_invalidation_enabled: bool = True,
        mitm_enabled: bool = True,
        mitm_certs_dir: str | Path = "certs",
        config_path: str | Path | None = None,
        config_repository: ConfigRepository | None = None,
        settings: RuntimeSettings | None = None,
    ) -> None:
        self.settings_state = RuntimeSettingsState(
            settings=settings,
            log_level=log_level,
            log_whitelist=log_whitelist or (),
            cache_invalidation_enabled=cache_invalidation_enabled,
            mitm_enabled=mitm_enabled,
            mitm_certs_dir=mitm_certs_dir,
        )
        self.configuration = RuntimeConfigurationService(
            settings=self.settings_state,
            repository=config_repository or JsonConfigRepository(),
            path=config_path,
        )
        self.traffic_rule_store = TrafficRuleStore()
        self.traffic_rules = TrafficRuleAdministrationService(
            self.traffic_rule_store,
            on_change=self.configuration.set_traffic_rules,
        )

    @property
    def config_path(self) -> Path | None:
        return self.configuration.path

    @property
    def config_repository(self) -> ConfigRepository:
        return self.configuration.repository

    @property
    def settings(self) -> RuntimeSettings:
        return self.settings_state.snapshot

    @property
    def log_level(self) -> int:
        return self.settings_state.log_level

    @property
    def cache_invalidation_enabled(self) -> bool:
        return self.settings_state.cache_invalidation_enabled

    @property
    def mitm_enabled(self) -> bool:
        return self.settings_state.mitm_enabled

    @property
    def mitm_certs_dir(self) -> Path:
        return self.settings_state.mitm_certs_dir

    def log_level_name(self) -> str:
        return self.settings_state.log_level_name()

    def set_log_level(self, value: str | int) -> int:
        return self.settings_state.set_log_level(value)

    def whitelist_entries(self) -> tuple[str, ...]:
        return self.settings_state.whitelist_entries()

    def set_cache_invalidation_enabled(self, enabled: bool) -> bool:
        return self.settings_state.set_cache_invalidation_enabled(enabled)

    def toggle_cache_invalidation(self) -> bool:
        return self.settings_state.toggle_cache_invalidation()

    def set_mitm_enabled(self, enabled: bool) -> bool:
        return self.settings_state.set_mitm_enabled(enabled)

    def set_mitm_certs_dir(self, value: str | Path) -> Path:
        return self.settings_state.set_mitm_certs_dir(value)

    def add_whitelist_entry(self, value: str) -> str:
        return self.settings_state.add_whitelist_entry(value)

    def remove_whitelist_entry(self, value: str) -> bool:
        return self.settings_state.remove_whitelist_entry(value)

    def clear_whitelist(self) -> None:
        self.settings_state.clear_whitelist()

    def should_log_for_host(self, host: str | None) -> bool:
        return self.settings_state.should_log_for_host(host)

    def attach_config_path(self, path: str | Path) -> None:
        self.configuration.attach(path)

    def to_config_document(self) -> ConfigDocument:
        return self.configuration.create_document()

    def apply_config_document(self, document: ConfigDocument) -> None:
        self.configuration.apply_document(document)

    def save(self) -> None:
        self.configuration.save()

    def add_static_response_rule(
        self,
        *,
        url: str,
        status_code: int = 200,
        reason: str = "OK",
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        method: str = "GET",
    ) -> str:
        rule_id = f"static-response-{len(self.traffic_rules.list_rules()) + 1}"
        self.traffic_rules.add_rule(
            TrafficRule(
                rule_id,
                rule_id,
                True,
                0,
                RulePhase.RESPOND,
                TrafficMatch(methods=(method,), url=url),
                RespondAction(status_code, reason, tuple((headers or {}).items()), body),
            )
        )
        return rule_id

    def add_open_editor_rule(self, url: str, *, method: str = "GET") -> str:
        rule_id = f"open-editor-{len(self.traffic_rules.list_rules()) + 1}"
        self.traffic_rules.add_rule(
            TrafficRule(
                rule_id,
                rule_id,
                True,
                0,
                RulePhase.RESPONSE,
                TrafficMatch(methods=(method,), url=url),
                OpenEditorAction(),
            )
        )
        return rule_id

    @classmethod
    def load_from_file(
        cls, path: str | Path, *, config_repository: ConfigRepository | None = None
    ) -> "RuntimeTestContext":
        repository = config_repository or JsonConfigRepository()
        document = repository.load(Path(path))
        return cls(config_path=path, config_repository=repository, settings=document.settings)


def runtime_dependencies(config: RuntimeTestContext) -> dict[str, object]:
    return {"settings": config.settings_state, "configuration": config.configuration}


def runtime_application_services(
    config: RuntimeTestContext,
    *,
    request_journal: RequestJournal | None = None,
    response_modifier: ResponseModifierService | None = None,
    proxy_base_url: str | None = None,
) -> RuntimeApplicationServices:
    from proxyscope.bootstrap.runtime_services import create_default_runtime_application_services

    return create_default_runtime_application_services(
        **runtime_dependencies(config),
        request_journal=request_journal or RequestJournal(),
        response_modifier=response_modifier or ResponseModifierService(),
        proxy_base_url=proxy_base_url,
    )


def processing_dependencies(config: RuntimeTestContext) -> dict[str, object]:
    return {"settings": config.settings_state, "traffic_rule_engine": TrafficRuleEngine(config.traffic_rule_store)}
