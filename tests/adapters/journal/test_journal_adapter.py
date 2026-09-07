from proxyscope.adapters.journal import JournalAdapter
from proxyscope.application.journal import RequestJournal


def test_journal_adapter_returns_live_snapshots_with_capture_metadata() -> None:
    journal = RequestJournal()
    adapter = JournalAdapter(journal)
    assert adapter.get_entry(1) is None
    request_id = journal.start_request(
        method="POST", path="/items", start_line="POST /items HTTP/1.1",
        headers={}, body=b"", client_ip="127.0.0.1", target_host="api.test",
        target_port=8443, protocol="https",
    )
    pending = adapter.get_entry(request_id)
    assert pending is not None
    assert pending.url == "https://api.test:8443/items"
    assert pending.method == "POST"
    assert pending.response is None

    journal.complete_request(
        request_id, status_code=201, reason="Created", start_line="HTTP/1.1 201 Created",
        headers={"Content-Type": "application/octet-stream"}, body=b"\x00\xff", body_size=10, duration_ms=1,
    )
    completed = adapter.get_entry(request_id)
    assert completed is not None and completed.response is not None
    assert completed.response.body == b"\x00\xff"
    assert completed.response.body_size == 10
    assert completed.response.headers == (("Content-Type", "application/octet-stream"),)
    assert completed.response.status_code == 201
    assert pending.response is None
    assert adapter.list_entries() == (completed,)

    journal.clear()
    assert adapter.list_entries() == ()
    assert adapter.get_entry(request_id) is None
