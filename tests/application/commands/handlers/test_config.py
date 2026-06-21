import tempfile
import unittest
from pathlib import Path

from proxyscope.policies.engine import PolicyEngine
from tests.application.commands.handlers._helpers import config_handler
from tests.support.runtime_context import RuntimeTestContext


class TestConfigCommandHandler(unittest.TestCase):
    def test_save_and_reload_report_updated_log_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "runtime.json"
            config = RuntimeTestContext.load_from_file(config_path)
            config.set_log_level("INFO")
            config.save()
            handler = config_handler(config)

            save_result = handler.execute(["config", "save"], on_cache_toggle=None)
            external = RuntimeTestContext.load_from_file(config_path)
            external.set_log_level("WARNING")
            external.add_open_editor_policy("https://example.com/hot", method="POST")
            external.save()

            reload_result = handler.execute(["config", "reload"], on_cache_toggle=None)

            self.assertIn("Config saved:", save_result.status_message)
            self.assertIn("Config reloaded:", reload_result.status_message)
            self.assertEqual(reload_result.updated_log_level, config.log_level)
            self.assertEqual(config.log_level_name(), "WARNING")
            self.assertTrue(
                PolicyEngine(config.policy_repository).should_modify_response_for_request(
                    method="POST",
                    url="https://example.com/hot",
                )
            )


if __name__ == "__main__":
    unittest.main()
