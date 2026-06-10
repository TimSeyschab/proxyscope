import threading
import unittest
from threading import Event

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.editing.modifier import PendingResponseEdit, ResponseModifierService
from proxyscope.proxy.forwarding import ForwardResponse


class TestResponseModifierService(unittest.TestCase):
    def test_returns_original_when_not_whitelisted(self) -> None:
        service = ResponseModifierService(policy_evaluator=RuntimeConfig(), interactive_enabled=True)
        response = ForwardResponse(200, "OK", {"X-Test": "a"}, b"hello")
        out = service.maybe_modify_response(request_url="https://example.com/a", method="GET", response=response)
        self.assertEqual(out.body, b"hello")
        self.assertEqual(out.headers.get("X-Test"), "a")

    def test_blocks_and_applies_edit_when_whitelisted(self) -> None:
        config = RuntimeConfig()
        config.add_modification_whitelist_entry("https://example.com/a")
        service = ResponseModifierService(policy_evaluator=config, interactive_enabled=True)
        response = ForwardResponse(200, "OK", {"Content-Type": "text/plain"}, b"original")

        result_holder: dict[str, ForwardResponse] = {}

        def run_modify() -> None:
            result_holder["response"] = service.maybe_modify_response(
                request_url="https://example.com/a",
                method="GET",
                response=response,
            )

        thread = threading.Thread(target=run_modify, daemon=True)
        thread.start()

        pending = None
        for _ in range(100):
            pending = service.poll_pending_edit()
            if pending is not None:
                break
            thread.join(timeout=0.01)
        self.assertIsNotNone(pending)
        assert pending is not None
        pending.apply(headers={"Content-Type": "text/plain"}, body=b"edited")
        thread.join(timeout=1.0)

        out = result_holder["response"]
        self.assertEqual(out.body, b"edited")

    def test_apply_recomputes_content_length(self) -> None:
        pending = PendingResponseEdit(
            request_url="https://example.com/a",
            method="GET",
            response=ForwardResponse(200, "OK", {"Content-Length": "8", "Transfer-Encoding": "chunked"}, b"original"),
            _done=Event(),
        )
        pending.apply(headers={"Content-Type": "text/plain", "Transfer-Encoding": "chunked"}, body=b"hello")
        out = pending.wait(timeout_s=0.1)
        lowered = {k.lower(): v for k, v in out.headers.items()}
        self.assertEqual(lowered["content-length"], "5")
        self.assertNotIn("transfer-encoding", lowered)
