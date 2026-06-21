import unittest

from proxyscope.policies.engine import PolicyEngine
from tests.application.commands.handlers._helpers import policy_handler
from tests.support.runtime_context import RuntimeTestContext


class TestPolicyCommandHandler(unittest.TestCase):
    def test_add_editor_static_and_quoted_static_body(self) -> None:
        config = RuntimeTestContext()
        handler = policy_handler(config)

        editor_result = handler.execute(
            ["policy", "add-editor", "POST", "https://example.com/path"],
            on_schedule_policy_edit=lambda _name: None,
        )
        static_result = handler.execute(
            ["policy", "add-static", "GET", "https://example.com/mock", "418", "text/plain", "hello quoted body"],
            on_schedule_policy_edit=lambda _name: None,
        )

        self.assertTrue(editor_result.handled)
        self.assertTrue(static_result.handled)
        self.assertEqual(config.open_editor_policy_entries(), ("POST https://example.com/path",))
        template = PolicyEngine(config.policy_repository).get_static_response_template_for_request(
            method="GET",
            url="https://example.com/mock",
        )
        self.assertIsNotNone(template)
        assert template is not None
        self.assertEqual(template.status_code, 418)
        self.assertEqual(template.body, b"hello quoted body")

    def test_enable_disable_remove_and_show_follow_matching_precedence(self) -> None:
        config = RuntimeTestContext()
        low = config.add_static_response_rule(
            url="https://example.com/base",
            name="low-priority",
            priority=0,
            method="GET",
        )
        config.add_static_response_rule(
            url="https://example.com/api",
            name="mid-priority-prefix",
            priority=5,
            method="GET",
            url_prefix=True,
        )
        config.add_static_response_rule(
            url="https://example.com/api/v1/users",
            name="high-priority-exact",
            priority=5,
            method="GET",
        )
        handler = policy_handler(config)

        show_result = handler.execute(["policy", "show"], on_schedule_policy_edit=lambda _name: None)
        self.assertLess(
            show_result.status_message.find("high-priority-exact"),
            show_result.status_message.find("mid-priority-prefix"),
        )
        self.assertLess(
            show_result.status_message.find("mid-priority-prefix"),
            show_result.status_message.find("low-priority"),
        )

        handler.execute(["policy", "disable", low], on_schedule_policy_edit=lambda _name: None)
        self.assertIsNone(
            PolicyEngine(config.policy_repository).get_static_response_template_for_request(
                method="GET",
                url="https://example.com/base",
            )
        )

        handler.execute(["policy", "enable", low], on_schedule_policy_edit=lambda _name: None)
        self.assertIsNotNone(
            PolicyEngine(config.policy_repository).get_static_response_template_for_request(
                method="GET",
                url="https://example.com/base",
            )
        )

        handler.execute(["policy", "remove", low], on_schedule_policy_edit=lambda _name: None)
        self.assertIsNone(config.get_policy_rule(low))

    def test_edit_schedules_existing_policy_only(self) -> None:
        config = RuntimeTestContext()
        rule_name = config.add_static_response_rule(url="https://example.com/mock", method="GET")
        handler = policy_handler(config)
        scheduled: list[str] = []

        missing_result = handler.execute(
            ["policy", "edit", "missing"],
            on_schedule_policy_edit=scheduled.append,
        )
        edit_result = handler.execute(
            ["policy", "edit", rule_name],
            on_schedule_policy_edit=scheduled.append,
        )

        self.assertEqual(missing_result.status_message, "Policy not found: missing")
        self.assertEqual(edit_result.status_message, f"Opening policy editor: {rule_name}")
        self.assertEqual(scheduled, [rule_name])


if __name__ == "__main__":
    unittest.main()
