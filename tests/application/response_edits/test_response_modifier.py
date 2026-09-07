import threading
import time
import unittest
from threading import Event

from proxyscope.application.artifacts import ArtifactStatus, InMemoryArtifactStore, ResponseEditArtifact
from proxyscope.application.processing.models import ExchangeResponse
from proxyscope.application.response_edits import PendingResponseEdit, ResponseModifierService


class TestResponseModifierService(unittest.TestCase):
    def test_returns_original_when_interactive_editor_is_disabled(self) -> None:
        service = ResponseModifierService(interactive_enabled=False)
        response = ExchangeResponse(200, "OK", {"X-Test": "a"}, b"hello")
        out = service.maybe_modify_response(request_url="https://example.com/a", method="GET", response=response)
        self.assertEqual(out.body, b"hello")
        self.assertEqual(out.headers.get("X-Test"), "a")

    def test_blocks_and_applies_edit_when_requested_by_pipeline(self) -> None:
        service = ResponseModifierService(interactive_enabled=True)
        response = ExchangeResponse(200, "OK", {"Content-Type": "text/plain"}, b"original")

        result_holder: dict[str, ExchangeResponse] = {}

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
            response=ExchangeResponse(200, "OK", {"Content-Length": "8", "Transfer-Encoding": "chunked"}, b"original"),
            _done=Event(),
        )
        pending.apply(headers={"Content-Type": "text/plain", "Transfer-Encoding": "chunked"}, body=b"hello")
        out = pending.wait(timeout_s=0.1)
        lowered = {k.lower(): v for k, v in out.headers.items()}
        self.assertEqual(lowered["content-length"], "5")
        self.assertNotIn("transfer-encoding", lowered)

    def test_timeout_keeps_original_response(self) -> None:
        service = ResponseModifierService(interactive_enabled=True, edit_timeout_s=0.01)
        response = ExchangeResponse(200, "OK", {}, b"original")

        out = service.maybe_modify_response(request_url="https://example.com/a", method="GET", response=response)

        self.assertIs(out, response)
        self.assertIsNone(service.poll_pending_edit())

    def test_cancel_pending_edits_unblocks_waiting_requests(self) -> None:
        service = ResponseModifierService(interactive_enabled=True, edit_timeout_s=10)
        response = ExchangeResponse(200, "OK", {}, b"original")
        result: list[ExchangeResponse] = []
        thread = threading.Thread(
            target=lambda: result.append(
                service.maybe_modify_response(request_url="https://example.com/a", method="GET", response=response)
            )
        )
        thread.start()
        for _ in range(100):
            if service.poll_pending_edit() is not None:
                break
            time.sleep(0.001)

        self.assertEqual(service.cancel_pending_edits(), 1)
        thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [response])

    def test_response_edit_artifact_records_limited_body_and_terminal_status(self) -> None:
        store = InMemoryArtifactStore(max_body_bytes=3)
        service = ResponseModifierService(interactive_enabled=True, artifact_store=store)
        artifact = ResponseEditArtifact(
            source_request_id=4,
            method="GET",
            request_url="https://example.com/a",
            headers=(),
            body=store.body_reference(b"original"),
            status=ArtifactStatus.RUNNING,
        )
        store.add(artifact)
        pending = PendingResponseEdit(
            request_url="https://example.com/a",
            method="GET",
            response=ExchangeResponse(200, "OK", {"Content-Type": "text/plain"}, b"original"),
            _done=Event(),
            source_request_id=4,
            artifact=artifact,
        )

        service.record_artifact_result(
            pending,
            status=ArtifactStatus.APPLIED,
            headers={"Content-Type": "text/plain"},
            body=b"edited-body",
        )

        stored = store.list_for_source(4)[0]
        self.assertEqual(stored.status, ArtifactStatus.APPLIED)
        self.assertEqual(stored.body.preview, b"edi")
        self.assertTrue(stored.body.truncated)
