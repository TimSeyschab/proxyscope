import logging
import unittest
from pathlib import Path

from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.config.settings import ConfigDocument, RuntimeSettings
from proxyscope.policies.models import OpenEditorAction, PolicyRule, RequestMatchRule


class _MemoryConfigRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[Path, ConfigDocument]] = []

    def load(self, path: Path) -> ConfigDocument:
        return self.saved[-1][1]

    def save(self, path: Path, document: ConfigDocument) -> None:
        self.saved.append((path, document))


class TestRuntimeSettingsState(unittest.TestCase):
    def test_mutations_update_snapshot(self) -> None:
        state = RuntimeSettingsState()

        state.set_log_level("DEBUG")
        state.add_whitelist_entry("https://example.com/path")
        state.set_mitm_certs_dir("custom-certs")

        self.assertEqual(state.snapshot.log_level, logging.DEBUG)
        self.assertEqual(state.snapshot.log_whitelist, ("example.com",))
        self.assertEqual(state.snapshot.mitm_certs_dir, Path("custom-certs"))

    def test_apply_replaces_state(self) -> None:
        state = RuntimeSettingsState()

        state.apply(RuntimeSettings.create(mitm_enabled=False))

        self.assertFalse(state.mitm_enabled)


class TestPolicyAdministrationService(unittest.TestCase):
    def test_policy_mutations_are_repository_backed(self) -> None:
        service = PolicyAdministrationService()

        service.add_open_editor("https://example.com/edit")
        rule = service.list_rules()[0]
        service.set_enabled(rule.name, enabled=False)
        service.remove_rule(rule.name)

        self.assertEqual(service.list_rules(), ())

    def test_generator_rules_are_not_consumed_during_initialization(self) -> None:
        rule = PolicyRule(
            name="generated",
            enabled=True,
            priority=0,
            action=OpenEditorAction(),
            match=RequestMatchRule(url_exact="https://example.com"),
        )

        service = PolicyAdministrationService(rules=(item for item in (rule,)))

        self.assertEqual(service.list_rules(), (rule,))


class TestRuntimeConfigurationService(unittest.TestCase):
    def test_explicit_save_persists_current_runtime_state(self) -> None:
        repository = _MemoryConfigRepository()
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


if __name__ == "__main__":
    unittest.main()
