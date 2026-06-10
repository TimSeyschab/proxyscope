import tempfile
import unittest
from pathlib import Path

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.editing.modifier import ResponseModifierService
from proxyscope.app.runtime.journal import RequestJournal
from proxyscope.application.contracts import PolicyUseCases, RequestUseCases, SessionUseCases, SettingsUseCases
from proxyscope.application.services import create_runtime_application_services


class TestRuntimeApplicationServices(unittest.TestCase):
    def setUp(self) -> None:
        self.config = RuntimeConfig()
        self.journal = RequestJournal()
        self.services = create_runtime_application_services(
            runtime_config=self.config,
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
