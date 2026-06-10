import logging
import unittest
from unittest.mock import patch

from proxyscope.adapters.observability.exchange_recorder import RequestResponseRecorder
from proxyscope.adapters.observability.logging import configure_logging
from proxyscope.application.journal import RequestJournal
from proxyscope.proxy.forwarding import ForwardResponse
from tests.support.runtime_context import RuntimeTestContext


class TestLoggingSetup(unittest.TestCase):
    def test_configure_logging_forwards_arguments_to_basic_config(self) -> None:
        with patch("proxyscope.adapters.observability.logging.logging.basicConfig") as basic_config_mock:
            configure_logging(level=logging.DEBUG)
        basic_config_mock.assert_called_once()
        kwargs = basic_config_mock.call_args.kwargs
        self.assertEqual(kwargs["level"], logging.DEBUG)
        self.assertIn("%(message)s", kwargs["format"])


class TestRequestResponseLogging(unittest.TestCase):
    def setUp(self) -> None:
        self.journal = RequestJournal()
        self.config = RuntimeTestContext()
        self.recorder = RequestResponseRecorder(settings=self.config.settings_state, request_journal=self.journal)

    def test_log_incoming_and_outgoing_persists_exchange(self) -> None:
        request_id = self.recorder.record_request(
            method="GET",
            path="/health",
            client_ip="127.0.0.1",
            headers={"Host": "example.com"},
            body=b"payload",
            target_host="example.com",
            target_port=443,
        )
        self.assertIsNotNone(request_id)

        self.recorder.record_response(
            ForwardResponse(status_code=200, reason="OK", headers={"Content-Type": "text/plain"}, body=b"ok"),
            request_id=request_id,
            duration_ms=2.3,
            client_ip="127.0.0.1",
            target_host="example.com",
        )

        entry = self.journal.get_entry(request_id or 0)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.request.method, "GET")
        self.assertIsNotNone(entry.response)
        assert entry.response is not None
        self.assertEqual(entry.response.status_code, 200)

    def test_log_incoming_skips_non_whitelisted_host(self) -> None:
        recorder = RequestResponseRecorder(
            settings=RuntimeTestContext(log_whitelist=("allowed.example",)).settings_state,
            request_journal=self.journal,
        )
        request_id = recorder.record_request(
            method="GET",
            path="/hidden",
            client_ip="127.0.0.1",
            headers={},
            target_host="blocked.example",
        )
        self.assertIsNone(request_id)
        self.assertEqual(self.journal.list_entries(), ())

    def test_log_mitm_request_response_with_invalid_start_line_uses_fallbacks(self) -> None:
        request_id = self.recorder.record_mitm_request(
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=443,
            start_line="BROKEN",
            headers={},
            body=b"x",
        )
        self.assertIsNotNone(request_id)

        self.recorder.record_mitm_response(
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=443,
            start_line="HTTP/1.1 not-a-number",
            headers={},
            body=b"resp",
            request_id=request_id,
        )

        entry = self.journal.get_entry(request_id or 0)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.request.method, "UNKNOWN")
        self.assertEqual(entry.request.path, "BROKEN")
        self.assertIsNotNone(entry.response)
        assert entry.response is not None
        self.assertEqual(entry.response.status_code, 0)

    def test_log_mitm_response_ignores_missing_request_id(self) -> None:
        self.recorder.record_mitm_response(
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=443,
            start_line="HTTP/1.1 200 OK",
            headers={},
            body=b"resp",
            request_id=None,
        )
        self.assertEqual(self.journal.list_entries(), ())
