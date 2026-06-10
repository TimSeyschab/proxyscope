import unittest
from threading import Event
from unittest.mock import patch

from proxyscope.adapters.editing.response_editor import _maybe_save_static_response_rule
from proxyscope.application.response_edits import PendingResponseEdit
from proxyscope.policies.engine import PolicyEngine
from proxyscope.proxy.forwarding import ForwardResponse
from tests.support.runtime_context import RuntimeTestContext


class TestResponseEditing(unittest.TestCase):
    def test_save_static_policy_from_edited_response(self) -> None:
        config = RuntimeTestContext()
        config.add_open_editor_policy("https://example.com/edited", method="GET")
        pending = PendingResponseEdit(
            request_url="https://example.com/edited",
            method="GET",
            response=ForwardResponse(
                status_code=200,
                reason="OK",
                headers={"Content-Type": "text/plain"},
                body=b"original",
            ),
            _done=Event(),
        )
        with patch("builtins.input", return_value="y"):
            policy_name = _maybe_save_static_response_rule(
                pending=pending,
                headers={"Content-Type": "text/plain"},
                body=b"edited-body",
                policies=config.policy_administration,
            )
        self.assertIsNotNone(policy_name)
        template = PolicyEngine(config.policy_repository).get_static_response_template_for_request(
            method="GET",
            url="https://example.com/edited",
        )
        self.assertIsNotNone(template)
        assert template is not None
        self.assertEqual(template.body, b"edited-body")
        self.assertEqual(template.status_code, 200)
        self.assertFalse(
            PolicyEngine(config.policy_repository).should_modify_response_for_request(
                method="GET",
                url="https://example.com/edited",
            )
        )

    def test_does_not_save_static_policy_when_user_declines(self) -> None:
        config = RuntimeTestContext()
        pending = PendingResponseEdit(
            request_url="https://example.com/edited",
            method="GET",
            response=ForwardResponse(
                status_code=200,
                reason="OK",
                headers={"Content-Type": "text/plain"},
                body=b"original",
            ),
            _done=Event(),
        )
        with patch("builtins.input", return_value="n"):
            policy_name = _maybe_save_static_response_rule(
                pending=pending,
                headers={"Content-Type": "text/plain"},
                body=b"edited-body",
                policies=config.policy_administration,
            )
        self.assertIsNone(policy_name)
        template = PolicyEngine(config.policy_repository).get_static_response_template_for_request(
            method="GET",
            url="https://example.com/edited",
        )
        self.assertIsNone(template)


if __name__ == "__main__":
    unittest.main()
