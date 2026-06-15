import tempfile
import unittest
from pathlib import Path

from proxyscope.adapters.factory import create_default_runtime_application_services
from proxyscope.application.contracts import PolicyUseCases, RequestUseCases, SessionUseCases, SettingsUseCases
from proxyscope.application.journal import RequestJournal
from proxyscope.application.response_edits import ResponseModifierService
from tests.support.runtime_context import RuntimeTestContext, runtime_dependencies


class TestRuntimeApplicationServices(unittest.TestCase):
    def setUp(self) -> None:
        self.config = RuntimeTestContext()
        self.journal = RequestJournal()
        self.services = create_default_runtime_application_services(
            **runtime_dependencies(self.config),
            request_journal=self.journal,
            response_modifier=ResponseModifierService(),
            proxy_base_url=None,
        )

    def test_services_implement_surface_independent_contracts(self) -> None:
        self.assertIsInstance(self.services.requests, RequestUseCases)
        self.assertIsInstance(self.services.sessions, SessionUseCases)
        self.assertIsInstance(self.services.settings, SettingsUseCases)
        self.assertIsInstance(self.services.policies, PolicyUseCases)

    def test_request_filtering_and_site_tracking_are_application_use_cases(self) -> None:
        self.journal.start_request(
            method="GET",
            path="/one",
            start_line="GET /one HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        self.services.requests.record_site_visit("example.com")

        self.assertEqual(
            self.services.requests.apply_filter(["host", "example.com"]), "Request filter: host=example.com"
        )
        self.assertEqual(len(self.services.requests.list_entries()), 1)
        self.assertEqual(self.services.requests.top_sites_summary(), "Top sites: example.com (1)")

    def test_request_window_returns_limited_slice_with_counts(self) -> None:
        for index in range(8):
            self.journal.start_request(
                method="GET",
                path=f"/{index}",
                start_line=f"GET /{index} HTTP/1.1",
                headers={},
                body=b"",
                client_ip="127.0.0.1",
                target_host="example.com",
                target_port=80,
                protocol="http",
            )

        window = self.services.requests.list_window(cursor=5, limit=3)

        self.assertEqual(window.offset, 4)
        self.assertEqual(window.total_count, 8)
        self.assertEqual(window.all_count, 8)
        self.assertEqual([entry.request.path for entry in window.entries], ["/3", "/2", "/1"])
        self.assertEqual(window.selected_entry.request.path if window.selected_entry else None, "/2")

    def test_request_window_counts_all_entries_when_filtered(self) -> None:
        self.journal.start_request(
            method="GET",
            path="/one",
            start_line="GET /one HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        self.journal.start_request(
            method="POST",
            path="/two",
            start_line="POST /two HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="api.example.com",
            target_port=80,
            protocol="http",
        )

        self.services.requests.apply_filter(["method", "POST"])
        window = self.services.requests.list_window(cursor=0, limit=10)

        self.assertEqual(window.total_count, 1)
        self.assertEqual(window.all_count, 2)
        self.assertEqual([entry.request.method for entry in window.entries], ["POST"])

    def test_session_service_roundtrips_journal_without_ui(self) -> None:
        self.journal.start_request(
            method="GET",
            path="/one",
            start_line="GET /one HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session.json"
            self.services.sessions.session(["save", str(path)])
            self.journal.clear()
            self.services.sessions.session(["load", str(path)])

        self.assertEqual(len(self.journal.list_entries()), 1)


if __name__ == "__main__":
    unittest.main()
