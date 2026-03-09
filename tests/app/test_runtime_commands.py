import tempfile
import unittest
from pathlib import Path

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.runtime.commands import RuntimeCommandService


class TestRuntimeCommandService(unittest.TestCase):
    def test_policy_edit_requires_existing_name(self) -> None:
        service = RuntimeCommandService(runtime_config=RuntimeConfig())
        scheduled: list[str] = []
        result = service.execute(
            "policy edit missing",
            on_cache_toggle=None,
            on_schedule_policy_edit=scheduled.append,
        )
        self.assertTrue(result.handled)
        self.assertEqual(result.status_message, "Policy not found: missing")
        self.assertEqual(scheduled, [])

    def test_loglevel_returns_updated_level(self) -> None:
        config = RuntimeConfig()
        service = RuntimeCommandService(runtime_config=config)
        result = service.execute(
            "loglevel DEBUG",
            on_cache_toggle=None,
            on_schedule_policy_edit=lambda _name: None,
        )
        self.assertTrue(result.handled)
        self.assertEqual(config.log_level_name(), "DEBUG")
        self.assertEqual(result.updated_log_level, config.log_level)

    def test_config_reload_reports_new_loglevel_for_hot_swap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "runtime.json"
            config = RuntimeConfig.load_from_file(config_path)
            config.set_log_level("INFO")
            config.save()

            external = RuntimeConfig.load_from_file(config_path)
            external.set_log_level("WARNING")
            external.save()

            service = RuntimeCommandService(runtime_config=config)
            result = service.execute(
                "config reload",
                on_cache_toggle=None,
                on_schedule_policy_edit=lambda _name: None,
            )
            self.assertTrue(result.handled)
            self.assertIn("Config reloaded:", result.status_message)
            self.assertEqual(result.updated_log_level, config.log_level)
            self.assertEqual(config.log_level_name(), "WARNING")


if __name__ == "__main__":
    unittest.main()
