import logging
import unittest
from pathlib import Path

from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.config.settings import RuntimeSettings
from tests.support.runtime_context import RuntimeTestContext, normalize_whitelist_entry


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


class TestRuntimeSettingsContext(unittest.TestCase):
    def test_empty_whitelist_logs_everything(self) -> None:
        config = RuntimeTestContext()
        self.assertTrue(config.should_log_for_host("example.com"))
        self.assertTrue(config.should_log_for_host(None))

    def test_non_empty_whitelist_filters_hosts(self) -> None:
        config = RuntimeTestContext(log_whitelist=["example.com"])
        self.assertTrue(config.should_log_for_host("example.com"))
        self.assertFalse(config.should_log_for_host("google.com"))
        self.assertFalse(config.should_log_for_host(None))

    def test_set_log_level(self) -> None:
        config = RuntimeTestContext()
        config.set_log_level("DEBUG")
        self.assertEqual(config.log_level, logging.DEBUG)

    def test_normalize_whitelist_entry_accepts_url(self) -> None:
        self.assertEqual(normalize_whitelist_entry("https://www.example.com/path"), "www.example.com")

    def test_cache_invalidation_toggle(self) -> None:
        config = RuntimeTestContext()
        self.assertTrue(config.cache_invalidation_enabled)
        config.toggle_cache_invalidation()
        self.assertFalse(config.cache_invalidation_enabled)
        config.set_cache_invalidation_enabled(True)
        self.assertTrue(config.cache_invalidation_enabled)

    def test_mitm_settings_can_be_updated(self) -> None:
        config = RuntimeTestContext()
        self.assertTrue(config.mitm_enabled)
        self.assertEqual(config.mitm_certs_dir, Path("certs"))

        config.set_mitm_enabled(False)
        config.set_mitm_certs_dir("custom-certs")

        self.assertFalse(config.mitm_enabled)
        self.assertEqual(config.mitm_certs_dir, Path("custom-certs"))


if __name__ == "__main__":
    unittest.main()
