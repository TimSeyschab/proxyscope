import tempfile
import unittest
from pathlib import Path

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.runtime.commands import RuntimeCommandService


class TestRuntimeCommandService(unittest.TestCase):
    def test_mitm_commands_update_runtime_config(self) -> None:
        config = RuntimeConfig()
        service = RuntimeCommandService(runtime_config=config)

        result = service.execute(
            "mitm off",
            on_cache_toggle=None,
            on_schedule_policy_edit=lambda _name: None,
        )
        self.assertTrue(result.handled)
        self.assertFalse(config.mitm_enabled)

        result = service.execute(
            "mitm certs-dir custom-certs",
            on_cache_toggle=None,
            on_schedule_policy_edit=lambda _name: None,
        )
        self.assertTrue(result.handled)
        self.assertEqual(config.mitm_certs_dir, Path("custom-certs"))

    def test_policy_prefix_and_priority_commands(self) -> None:
        config = RuntimeConfig()
        service = RuntimeCommandService(runtime_config=config)

        add_result = service.execute(
            "policy add-editor-prefix GET https://example.com/api",
            on_cache_toggle=None,
            on_schedule_policy_edit=lambda _name: None,
        )
        self.assertTrue(add_result.handled)
        self.assertTrue(
            config.should_modify_response_for_request(
                method="GET",
                url="https://example.com/api/v1/users",
            )
        )

        rule_name = config.policy_rules()[0].name
        priority_result = service.execute(
            f"policy set-priority {rule_name} 12",
            on_cache_toggle=None,
            on_schedule_policy_edit=lambda _name: None,
        )
        self.assertTrue(priority_result.handled)
        self.assertEqual(config.policy_rules()[0].priority, 12)

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

    def test_policy_show_uses_matching_precedence_order(self) -> None:
        config = RuntimeConfig()
        config.add_static_response_rule(
            url="https://example.com/base",
            method="GET",
            priority=0,
            name="low-priority",
        )
        config.add_static_response_rule(
            url="https://example.com/api",
            method="GET",
            priority=5,
            url_prefix=True,
            name="mid-priority-prefix",
        )
        config.add_static_response_rule(
            url="https://example.com/api/v1/users",
            method="GET",
            priority=5,
            name="high-priority-exact",
        )
        service = RuntimeCommandService(runtime_config=config)

        result = service.execute(
            "policy show",
            on_cache_toggle=None,
            on_schedule_policy_edit=lambda _name: None,
        )
        self.assertTrue(result.handled)
        self.assertIn("Policies (3):", result.status_message)
        self.assertLess(
            result.status_message.find("high-priority-exact"),
            result.status_message.find("mid-priority-prefix"),
        )
        self.assertLess(
            result.status_message.find("mid-priority-prefix"),
            result.status_message.find("low-priority"),
        )

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
