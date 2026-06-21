import unittest
from pathlib import Path

from tests.application.commands.handlers._helpers import settings_handler
from tests.support.runtime_context import RuntimeTestContext


class TestSettingsCommandHandler(unittest.TestCase):
    def test_loglevel_returns_updated_level(self) -> None:
        config = RuntimeTestContext()
        handler = settings_handler(config)

        result = handler.execute(["loglevel", "DEBUG"], on_cache_toggle=None)

        self.assertTrue(result.handled)
        self.assertEqual(config.log_level_name(), "DEBUG")
        self.assertEqual(result.updated_log_level, config.log_level)

    def test_whitelist_add_remove_and_mitm_update_runtime_config(self) -> None:
        config = RuntimeTestContext()
        handler = settings_handler(config)

        handler.execute(["whitelist", "add", "https://example.com/path"], on_cache_toggle=None)
        self.assertEqual(config.whitelist_entries(), ("example.com",))

        handler.execute(["wl", "remove", "example.com"], on_cache_toggle=None)
        self.assertEqual(config.whitelist_entries(), ())

        handler.execute(["mitm", "off"], on_cache_toggle=None)
        handler.execute(["mitm", "certs-dir", "custom-certs"], on_cache_toggle=None)
        self.assertFalse(config.mitm_enabled)
        self.assertEqual(config.mitm_certs_dir, Path("custom-certs"))

    def test_cache_command_invokes_toggle_hook(self) -> None:
        config = RuntimeTestContext()
        handler = settings_handler(config)
        called = {"count": 0}

        handler.execute(
            ["cache", "on"],
            on_cache_toggle=lambda: called.__setitem__("count", called["count"] + 1),
        )

        self.assertTrue(config.cache_invalidation_enabled)
        self.assertEqual(called["count"], 1)


if __name__ == "__main__":
    unittest.main()
