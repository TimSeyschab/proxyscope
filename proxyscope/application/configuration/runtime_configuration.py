from dataclasses import replace
from pathlib import Path

from proxyscope.application.configuration.component_settings import ComponentSettings
from proxyscope.application.configuration.models import ConfigDocument, EventStoreSettings
from proxyscope.application.configuration.repository import ConfigRepository
from proxyscope.application.runtime_settings import RuntimeSettingsState


class RuntimeConfigurationService:
    def __init__(
        self,
        *,
        settings: RuntimeSettingsState,
        repository: ConfigRepository,
        path: str | Path | None = None,
        event_store: EventStoreSettings = EventStoreSettings(),
        traffic_rules: tuple[dict[str, object], ...] = (),
        components: ComponentSettings = ComponentSettings(),
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._path = Path(path) if path is not None else None
        self._event_store = event_store
        self._traffic_rules = traffic_rules
        self._components = components

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def repository(self) -> ConfigRepository:
        return self._repository

    def attach(self, path: str | Path) -> None:
        self._path = Path(path)

    def create_document(self) -> ConfigDocument:
        return ConfigDocument(
            settings=self._settings.snapshot,
            event_store=self._event_store,
            traffic_rules=self._traffic_rules,
            components=self._components,
        )

    def apply_document(self, document: ConfigDocument) -> None:
        self._settings.apply(document.settings)
        self._event_store = document.event_store
        self._traffic_rules = document.traffic_rules
        self._components = document.components

    def set_enabled_components(self, component_ids: tuple[str, ...]) -> None:
        self._components = replace(self._components, enabled_components=component_ids)
        self.save()

    def set_traffic_rules(self, rules: tuple[dict[str, object], ...]) -> None:
        self._traffic_rules = rules
        self.save()

    def set_component_configuration(self, component_id: str, configuration: dict[str, object]) -> None:
        normalized = component_id.strip().lower()
        if not normalized:
            raise ValueError("Component ID must not be empty.")
        configurations = dict(self._components.configurations)
        configurations[normalized] = dict(configuration)
        self._components = replace(self._components, configurations=tuple(configurations.items()))
        self.save()

    def save(self, path: str | Path | None = None) -> Path | None:
        if path is not None:
            self.attach(path)
        if self._path is None:
            return None
        self._repository.save(self._path, self.create_document())
        return self._path

    def reload(self) -> bool:
        if self._path is None:
            return False
        self.apply_document(self._repository.load(self._path))
        return True
