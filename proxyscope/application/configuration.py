from pathlib import Path

from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.config.repository import ConfigRepository
from proxyscope.config.settings import ConfigDocument


class RuntimeConfigurationService:
    def __init__(
        self,
        *,
        settings: RuntimeSettingsState,
        policies: PolicyAdministrationService,
        repository: ConfigRepository,
        path: str | Path | None = None,
    ) -> None:
        self._settings = settings
        self._policies = policies
        self._repository = repository
        self._path = Path(path) if path is not None else None

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def repository(self) -> ConfigRepository:
        return self._repository

    def attach(self, path: str | Path) -> None:
        self._path = Path(path)

    def create_document(self) -> ConfigDocument:
        return ConfigDocument(settings=self._settings.snapshot, policies=self._policies.list_rules())

    def apply_document(self, document: ConfigDocument) -> None:
        self._settings.apply(document.settings)
        self._policies.replace_all(document.policies)

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
