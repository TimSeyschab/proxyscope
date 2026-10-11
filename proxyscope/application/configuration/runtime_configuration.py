import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from proxyscope.application.configuration.component_settings import ComponentSettings
from proxyscope.application.configuration.models import ConfigDocument, EventStoreSettings
from proxyscope.application.configuration.repository import ConfigRepository
from proxyscope.application.configuration.serialization import parse_config_payload, serialize_config_document
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
        self._document_applied_handlers: list[Callable[[ConfigDocument], None]] = []

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
        for handler in tuple(self._document_applied_handlers):
            handler(document)

    def add_document_applied_handler(self, handler: Callable[[ConfigDocument], None]) -> None:
        """Register a runtime consumer that must reflect a newly applied document."""
        self._document_applied_handlers.append(handler)

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

    def load_json(self) -> str:
        """Return the current runtime document in the canonical editable JSON form."""
        return json.dumps(serialize_config_document(self.create_document()), indent=2, ensure_ascii=True) + "\n"

    def save_json(self, content: str) -> str:
        """Validate, persist, and apply an edited configuration document."""
        if self._path is None:
            raise ValueError("No attached config path. Start proxyscope with --config.")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
        document = parse_config_payload(payload)
        self._repository.save(self._path, document)
        self.apply_document(document)
        return str(self._path)
