import unittest
from threading import Event
from unittest.mock import patch

from proxyscope.adapters.editing.response_editor import edit_pending_response_with_external_editor
from proxyscope.application.processing.models import ExchangeResponse
from proxyscope.application.response_edits import PendingResponseEdit


class TestResponseEditing(unittest.TestCase):
    def test_successful_edit_returns_edited_payload_without_extra_prompt(self) -> None:
        pending = PendingResponseEdit(
            request_url="https://example.com/edited",
            method="GET",
            response=ExchangeResponse(
                status_code=200,
                reason="OK",
                headers={"Content-Type": "text/plain"},
                body=b"original",
            ),
            _done=Event(),
        )

        with (
            patch("proxyscope.adapters.editing.response_editor._resolve_editor_command", return_value="editor"),
            patch("proxyscope.adapters.editing.response_editor._run_editor"),
            patch("builtins.input", side_effect=AssertionError("response editor must not prompt")),
        ):
            result = edit_pending_response_with_external_editor(pending)

        self.assertTrue(result.success)
        self.assertEqual(result.headers, {"Content-Type": "text/plain"})
        self.assertEqual(result.body, b"original")
        self.assertEqual(
            pending.wait(),
            ExchangeResponse(200, "OK", {"Content-Type": "text/plain", "Content-Length": "8"}, b"original"),
        )

    def test_editor_failure_keeps_original_response(self) -> None:
        pending = PendingResponseEdit(
            request_url="https://example.com/edited",
            method="GET",
            response=ExchangeResponse(
                status_code=200,
                reason="OK",
                headers={"Content-Type": "text/plain"},
                body=b"original",
            ),
            _done=Event(),
        )

        with (
            patch("proxyscope.adapters.editing.response_editor._resolve_editor_command", return_value="editor"),
            patch("proxyscope.adapters.editing.response_editor._run_editor", side_effect=RuntimeError("cancelled")),
        ):
            result = edit_pending_response_with_external_editor(pending)

        self.assertFalse(result.success)
        self.assertEqual(pending.wait(), pending.response)


if __name__ == "__main__":
    unittest.main()
