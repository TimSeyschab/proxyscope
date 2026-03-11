import unittest

from proxyscope.app.runtime.journal import RequestJournal


class TestRequestJournal(unittest.TestCase):
    def test_tracks_request_lifecycle(self) -> None:
        journal = RequestJournal()
        request_id = journal.start_request(
            method="POST",
            path="/submit",
            start_line="POST /submit HTTP/1.1",
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
            headers={"Content-Length": "2"},
            body=b"ok",
            duration_ms=21.5,
        )

        entries = journal.list_entries()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.request_id, request_id)
        self.assertEqual(entry.request.method, "POST")
        self.assertEqual(entry.request.path, "/submit")
        self.assertEqual(entry.request.body, b'{"ok":true}')
        assert entry.response is not None
        self.assertEqual(entry.response.status_code, 201)
        self.assertEqual(entry.response.reason, "Created")
        self.assertEqual(entry.response.body_preview, "ok")

    def test_caps_history(self) -> None:
        journal = RequestJournal(max_entries=2)
        first = journal.start_request(
            method="GET",
            path="/1",
            start_line="GET /1 HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        journal.start_request(
            method="GET",
            path="/2",
            start_line="GET /2 HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        journal.start_request(
            method="GET",
            path="/3",
            start_line="GET /3 HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )

        ids = [entry.request_id for entry in journal.list_entries()]
        self.assertNotIn(first, ids)
        self.assertEqual(len(ids), 2)

    def test_body_preview_escapes_nul_bytes(self) -> None:
        journal = RequestJournal()
        request_id = journal.start_request(
            method="POST",
            path="/bin",
            start_line="POST /bin HTTP/1.1",
            headers={},
            body=b"abc\x00def",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        entry = journal.get_entry(request_id)
        assert entry is not None
        self.assertEqual(entry.request.body_preview, "abc\\x00def")
        self.assertEqual(entry.request.body, b"abc\x00def")
