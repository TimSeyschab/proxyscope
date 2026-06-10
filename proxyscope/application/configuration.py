from pathlib import Path

from proxyscope.app.config.runtime import RuntimeConfig


class RuntimeConfigService:
    def __init__(self, runtime_config: RuntimeConfig) -> None:
        self._runtime_config = runtime_config

    def save(self, path: str | Path | None = None) -> Path | None:
        if path is not None:
            return self._runtime_config.save_to_path(path)
        current = self._runtime_config.config_path
        if current is None:
            return None
        self._runtime_config.save()
        return current

    def reload(self) -> bool:
        path = self._runtime_config.config_path
        if path is None:
            return False
        document = self._runtime_config.config_repository.load(path)
        self._runtime_config.apply_config_document(document)
        return True
