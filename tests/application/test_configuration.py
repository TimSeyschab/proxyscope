import tempfile
import unittest
from pathlib import Path

from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.config.settings import ConfigDocument, RuntimeSettings
from proxyscope.policies.engine import PolicyEngine
from tests.support.runtime_context import RuntimeTestContext


class _StaticConfigRepository:
    def __init__(self, document: ConfigDocument) -> None:
        self.document = document
        self.saved: tuple[Path, ConfigDocument] | None = None

    def load(self, path: Path) -> ConfigDocument:
        return self.document

    def save(self, path: Path, document: ConfigDocument) -> None:
        self.saved = (path, document)


class _RecordingConfigRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[Path, ConfigDocument]] = []

    def load(self, path: Path) -> ConfigDocument:
        return self.saved[-1][1]

    def save(self, path: Path, document: ConfigDocument) -> None:
        self.saved.append((path, document))


class TestRuntimeConfigurationService(unittest.TestCase):
    def test_reload_applies_repository_document(self) -> None:
        repository = _StaticConfigRepository(
            ConfigDocument(settings=RuntimeSettings.create(log_level=10, mitm_enabled=False))
        )
        config = RuntimeTestContext(config_path="config.json", config_repository=repository)

        reloaded = config.configuration.reload()

        self.assertTrue(reloaded)
        self.assertEqual(config.log_level, 10)
        self.assertFalse(config.mitm_enabled)

    def test_save_uses_repository_and_can_attach_path(self) -> None:
        repository = _StaticConfigRepository(ConfigDocument(settings=RuntimeSettings()))
        config = RuntimeTestContext(config_repository=repository)
        service = config.configuration

        self.assertIsNone(service.save())
        saved_path = service.save("demo.json")

        self.assertEqual(saved_path, Path("demo.json"))
        self.assertIsNotNone(repository.saved)

    def test_explicit_save_persists_current_runtime_state(self) -> None:
        repository = _RecordingConfigRepository()
        settings = RuntimeSettingsState()
        policies = PolicyAdministrationService()
        configuration = RuntimeConfigurationService(
            settings=settings,
            policies=policies,
            repository=repository,
            path="config.json",
        )
        settings.set_mitm_enabled(False)
        policies.add_open_editor("https://example.com/edit")
        configuration.save()

        self.assertEqual(len(repository.saved), 1)
        self.assertFalse(repository.saved[-1][1].settings.mitm_enabled)
        self.assertEqual(len(repository.saved[-1][1].policies), 1)

    def test_runtime_configuration_persists_mutations_when_saved_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "runtime-config.json"
            config = RuntimeTestContext.load_from_file(config_path)

            config.set_log_level("DEBUG")
            config.add_whitelist_entry("https://example.com")
            config.set_mitm_enabled(False)
            config.set_mitm_certs_dir("cert-bundle")
            config.add_modification_whitelist_entry("https://example.com/edit", method="POST")
            config.add_static_response_rule(
                url="https://example.com/mock",
                status_code=201,
                reason="Created",
                headers={"Content-Type": "application/json"},
                body=b'{"mock":true}',
                method="GET",
            )
            config.save()

            reloaded = RuntimeTestContext.load_from_file(config_path)
            self.assertEqual(reloaded.log_level_name(), "DEBUG")
            self.assertEqual(reloaded.whitelist_entries(), ("example.com",))
            self.assertFalse(reloaded.mitm_enabled)
            self.assertEqual(reloaded.mitm_certs_dir, Path("cert-bundle"))
            self.assertTrue(
                PolicyEngine(reloaded.policy_repository).should_modify_response_for_request(
                    method="POST",
                    url="https://example.com/edit",
                )
            )
            template = PolicyEngine(reloaded.policy_repository).get_static_response_template_for_request(
                method="GET",
                url="https://example.com/mock",
            )
            self.assertIsNotNone(template)
            assert template is not None
            self.assertEqual(template.status_code, 201)
            self.assertEqual(template.reason, "Created")
            self.assertEqual(template.body, b'{"mock":true}')

    def test_reload_from_attached_file_hot_swaps_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "runtime-config.json"
            config = RuntimeTestContext.load_from_file(config_path)
            config.set_log_level("INFO")
            config.set_cache_invalidation_enabled(True)
            config.set_mitm_enabled(True)
            config.set_mitm_certs_dir("before-certs")
            config.add_whitelist_entry("https://before.example")
            config.add_open_editor_policy("https://before.example/edit", method="GET")
            config.save()

            external = RuntimeTestContext.load_from_file(config_path)
            external.set_log_level("DEBUG")
            external.set_cache_invalidation_enabled(False)
            external.set_mitm_enabled(False)
            external.set_mitm_certs_dir("after-certs")
            external.clear_whitelist()
            external.add_whitelist_entry("https://after.example")
            external.clear_open_editor_policies()
            external.add_open_editor_policy("https://after.example/edit", method="POST")
            external.save()

            reloaded = config.configuration.reload()
            self.assertTrue(reloaded)
            self.assertEqual(config.log_level_name(), "DEBUG")
            self.assertFalse(config.cache_invalidation_enabled)
            self.assertFalse(config.mitm_enabled)
            self.assertEqual(config.mitm_certs_dir, Path("after-certs"))
            self.assertEqual(config.whitelist_entries(), ("after.example",))
            self.assertFalse(
                PolicyEngine(config.policy_repository).should_modify_response_for_request(
                    method="GET", url="https://before.example/edit"
                )
            )
            self.assertTrue(
                PolicyEngine(config.policy_repository).should_modify_response_for_request(
                    method="POST", url="https://after.example/edit"
                )
            )


if __name__ == "__main__":
    unittest.main()
