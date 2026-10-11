import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proxyscope.application.configuration import (
    ConfigDocument,
    ConfigRepository,
    JsonConfigRepository,
    RuntimeConfigurationService,
    RuntimeSettings,
    serialize_config_document,
)
from proxyscope.application.runtime_settings import RuntimeSettingsState


class TestJsonConfigRepository(unittest.TestCase):
    def test_missing_file_loads_default_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            document = JsonConfigRepository().load(Path(tmp_dir) / "missing.json")

        self.assertEqual(document, ConfigDocument(settings=RuntimeSettings()))

    def test_implements_repository_contract_and_roundtrips(self) -> None:
        repository = JsonConfigRepository()
        self.assertIsInstance(repository, ConfigRepository)
        document = ConfigDocument(settings=RuntimeSettings.create(log_whitelist=("example.com",)))

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "config.json"
            repository.save(path, document)

            self.assertEqual(repository.load(path), document)

    def test_save_is_atomic_when_replace_fails(self) -> None:
        repository = JsonConfigRepository()
        original = '{"original":true}\n'
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "config.json"
            path.write_text(original, encoding="utf-8")

            with patch(
                "proxyscope.application.configuration.repository.os.replace", side_effect=OSError("replace failed")
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    repository.save(path, ConfigDocument(settings=RuntimeSettings()))

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_invalid_json_error_contains_location(self) -> None:
        repository = JsonConfigRepository()
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "config.json"
            path.write_text('{"broken":', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"line 1, column"):
                repository.load(path)

    def test_save_json_validates_persists_and_applies_configuration(self) -> None:
        repository = JsonConfigRepository()
        original = ConfigDocument(settings=RuntimeSettings.create(mitm_enabled=True))
        edited = ConfigDocument(settings=RuntimeSettings.create(mitm_enabled=False))
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "config.json"
            repository.save(path, original)
            service = RuntimeConfigurationService(
                settings=RuntimeSettingsState(settings=original.settings),
                repository=repository,
                path=path,
            )

            saved_path = service.save_json(json.dumps(serialize_config_document(edited)))

            self.assertEqual(saved_path, str(path))
            self.assertFalse(repository.load(path).settings.mitm_enabled)
            self.assertFalse(service.create_document().settings.mitm_enabled)

    def test_save_json_rejects_invalid_content_without_overwriting_the_file(self) -> None:
        repository = JsonConfigRepository()
        original = ConfigDocument(settings=RuntimeSettings())
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "config.json"
            repository.save(path, original)
            expected_content = path.read_text(encoding="utf-8")
            service = RuntimeConfigurationService(
                settings=RuntimeSettingsState(settings=original.settings),
                repository=repository,
                path=path,
            )

            with self.assertRaisesRegex(ValueError, "Invalid JSON"):
                service.save_json('{"schema_version":')

            self.assertEqual(path.read_text(encoding="utf-8"), expected_content)


if __name__ == "__main__":
    unittest.main()
