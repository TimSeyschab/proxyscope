import unittest
from threading import Event
from unittest.mock import patch

from proxyscope.app.config.runtime import RuntimeConfig, set_runtime_config
from proxyscope.app.editing.modifier import PendingResponseEdit
from proxyscope.app.editing.response import _maybe_save_static_response_rule
from proxyscope.proxy.forwarding import ForwardResponse


class TestResponseEditing(unittest.TestCase):
    def tearDown(self) -> None:
        set_runtime_config(RuntimeConfig())

    def test_save_static_policy_from_edited_response(self) -> None:
        config = RuntimeConfig()
        set_runtime_config(config)
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
            )
        self.assertIsNotNone(policy_name)
        template = config.get_static_response_template_for_request(
            method="GET",
            url="https://example.com/edited",
        )
        self.assertIsNotNone(template)
        assert template is not None
        self.assertEqual(template.body, b"edited-body")
        self.assertEqual(template.status_code, 200)
        self.assertFalse(
            config.should_modify_response_for_request(
                method="GET",
                url="https://example.com/edited",
            )
        )

    def test_does_not_save_static_policy_when_user_declines(self) -> None:
        config = RuntimeConfig()
        set_runtime_config(config)
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
            )
        self.assertIsNone(policy_name)
        template = config.get_static_response_template_for_request(
            method="GET",
            url="https://example.com/edited",
        )
        self.assertIsNone(template)


if __name__ == "__main__":
    unittest.main()
