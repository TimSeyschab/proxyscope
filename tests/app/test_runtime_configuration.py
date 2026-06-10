import unittest
from pathlib import Path

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.application.configuration import RuntimeConfigService
from proxyscope.config.settings import ConfigDocument, RuntimeSettings


class _MemoryConfigRepository:
    def __init__(self, document: ConfigDocument) -> None:
        self.document = document
        self.saved: tuple[Path, ConfigDocument] | None = None

    def load(self, path: Path) -> ConfigDocument:
        return self.document

    def save(self, path: Path, document: ConfigDocument) -> None:
        self.saved = (path, document)


class TestRuntimeConfigService(unittest.TestCase):
    def test_reload_applies_repository_document(self) -> None:
        repository = _MemoryConfigRepository(
            ConfigDocument(settings=RuntimeSettings.create(log_level=10, mitm_enabled=False))
        )
        config = RuntimeConfig(config_path="config.json", config_repository=repository)

        reloaded = RuntimeConfigService(config).reload()

        self.assertTrue(reloaded)
        self.assertEqual(config.log_level, 10)
        self.assertFalse(config.mitm_enabled)

    def test_save_uses_repository_and_can_attach_path(self) -> None:
        repository = _MemoryConfigRepository(ConfigDocument(settings=RuntimeSettings()))
        config = RuntimeConfig(config_repository=repository)
        service = RuntimeConfigService(config)

        self.assertIsNone(service.save())
        saved_path = service.save("demo.json")

        self.assertEqual(saved_path, Path("demo.json"))
        self.assertIsNotNone(repository.saved)


if __name__ == "__main__":
    unittest.main()
