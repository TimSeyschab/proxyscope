import json
import tempfile
import unittest
from pathlib import Path

from proxyscope.adapters.sessions.json_export import export_entries, load_entries_from_json
from proxyscope.application.journal import RequestJournal


class TestRuntimeExporting(unittest.TestCase):
    def _entries(self) -> list:
        journal = RequestJournal()
        request_id = journal.start_request(
            method="POST",
            path="/export",
            start_line="POST /export HTTP/1.1",
            headers={"Content-Type": "application/json"},
            body=b'{"ok":true}',
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=443,
            protocol="https-mitm",
        )
        journal.complete_request(
            request_id,
            status_code=201,
            reason="Created",
            start_line="HTTP/1.1 201 Created",
            headers={"Content-Type": "application/json"},
            body=b'{"created":true}',
            duration_ms=12.5,
            body_size=16,
        )
        return list(journal.list_entries())

    def test_export_json_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "snapshot.json"
            export_entries(self._entries(), format_name="json", destination=path)

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["entries"]), 1)
            entry = payload["entries"][0]
            self.assertEqual(entry["request"]["body_text"], '{"ok":true}')
            self.assertEqual(entry["response"]["body_size"], 16)

    def test_export_har_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "snapshot.har"
            export_entries(self._entries(), format_name="har", destination=path)

            payload = json.loads(path.read_text(encoding="utf-8"))
            entries = payload["log"]["entries"]
            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertEqual(entry["request"]["method"], "POST")
            self.assertEqual(entry["response"]["status"], 201)
            self.assertEqual(entry["response"]["content"]["size"], 16)

    def test_export_rejects_unknown_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "snapshot.txt"
            with self.assertRaisesRegex(ValueError, "Unsupported export format"):
                export_entries(self._entries(), format_name="txt", destination=path)

    def test_load_entries_from_json_roundtrips_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "snapshot.json"
            export_entries(self._entries(), format_name="json", destination=path)

            entries = load_entries_from_json(path)

            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertEqual(entry.request.method, "POST")
            self.assertEqual(entry.request.body, b'{"ok":true}')
            assert entry.response is not None
            self.assertEqual(entry.response.status_code, 201)


if __name__ == "__main__":
    unittest.main()
