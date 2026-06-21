import unittest

from proxyscope.application.commands import RuntimeCommandService
from tests.support.runtime_context import RuntimeTestContext, runtime_dependencies


class TestRuntimeCommandService(unittest.TestCase):
    def test_unknown_command_is_not_handled(self) -> None:
        service = RuntimeCommandService(**runtime_dependencies(RuntimeTestContext()))

        result = service.execute(
            "not-a-command",
            on_cache_toggle=None,
            on_schedule_policy_edit=lambda _name: None,
        )

        self.assertFalse(result.handled)

    def test_invalid_quoted_command_reports_syntax_error(self) -> None:
        service = RuntimeCommandService(**runtime_dependencies(RuntimeTestContext()))

        result = service.execute(
            'policy add-editor "unterminated',
            on_cache_toggle=None,
            on_schedule_policy_edit=lambda _name: None,
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.status_message, "Invalid command syntax: No closing quotation")

    def test_dispatches_to_runtime_command_groups(self) -> None:
        config = RuntimeTestContext()
        service = RuntimeCommandService(**runtime_dependencies(config))
        scheduled: list[str] = []
        rule_name = config.add_static_response_rule(url="https://example.com/mock", method="GET")

        loglevel_result = service.execute_parts(
            ["loglevel", "DEBUG"],
            on_cache_toggle=None,
            on_schedule_policy_edit=scheduled.append,
        )
        edit_result = service.execute_parts(
            ["pol", "edit", rule_name],
            on_cache_toggle=None,
            on_schedule_policy_edit=scheduled.append,
        )

        self.assertEqual(config.log_level_name(), "DEBUG")
        self.assertEqual(loglevel_result.updated_log_level, config.log_level)
        self.assertEqual(edit_result.status_message, f"Opening policy editor: {rule_name}")
        self.assertEqual(scheduled, [rule_name])


if __name__ == "__main__":
    unittest.main()
