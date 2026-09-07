from datetime import UTC, datetime, timedelta

from proxyscope.adapters.event_store import SQLiteEventStore
from proxyscope.application.event_store import EventStoreWriter
from proxyscope.application.events import (
    ArtifactRecorded,
    EventBus,
    RequestBodyCaptured,
    RequestObserved,
    ResponseObserved,
)
from proxyscope.application.journal import RequestJournal
from proxyscope.application.observability import RequestResponseRecorder
from proxyscope.application.processing.models import ExchangeResponse
from proxyscope.application.runtime_settings import RuntimeSettingsState


def _request(*, request_id: int = 17, occurred_at: datetime | None = None) -> RequestObserved:
    return RequestObserved(
        request_id=request_id,
        occurred_at=occurred_at or datetime.now(UTC),
        method="POST",
        path="/items",
        target_host="api.example.test",
        target_port=443,
        protocol="https",
    )


def test_stores_events_with_versioned_payload_and_metadata(tmp_path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    event = _request()

    store.append(event)

    stored = store.list_events(request_id=17)
    assert len(stored) == 1
    assert stored[0].event_id == event.event_id
    assert stored[0].payload_version == 1
    assert stored[0].payload["method"] == "POST"
    assert stored[0].target_host == "api.example.test"
    assert stored[0].method == "POST"
    store.close()


def test_filters_events_by_time_window(tmp_path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    now = datetime.now(UTC)
    store.append(_request(request_id=1, occurred_at=now - timedelta(hours=2)))
    expected = _request(request_id=2, occurred_at=now)
    store.append(expected)

    events = store.list_events(occurred_after=now - timedelta(minutes=1), occurred_before=now + timedelta(minutes=1))

    assert [event.event_id for event in events] == [expected.event_id]
    store.close()


def test_truncates_body_to_base64_preview(tmp_path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3", max_body_bytes=4)
    store.append(RequestBodyCaptured(request_id=17, body_size=8, body=b"abcdefgh"))

    payload = store.list_events(request_id=17)[0].payload

    assert payload["body"] == {"encoding": "base64", "content": "YWJjZA==", "size": 8, "truncated": True}
    store.close()


def test_retention_limits_event_count_and_age(tmp_path) -> None:
    now = datetime.now(UTC)
    store = SQLiteEventStore(tmp_path / "events.sqlite3", max_events=2, max_age_days=1)
    store.append(_request(request_id=1, occurred_at=now - timedelta(days=2)))
    store.append(_request(request_id=2, occurred_at=now - timedelta(minutes=2)))
    store.append(_request(request_id=3, occurred_at=now - timedelta(minutes=1)))
    store.append(ResponseObserved(request_id=4, status_code=200, reason="OK", body_size=0))

    assert [event.request_id for event in store.list_events()] == [3, 4]
    store.close()


def test_recorder_persists_events_without_treating_journal_as_audit_source(tmp_path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    bus = EventBus()
    bus.subscribe_async(EventStoreWriter(store))
    journal = RequestJournal()
    recorder = RequestResponseRecorder(settings=RuntimeSettingsState(), request_journal=journal, event_bus=bus)

    request_id = recorder.record_request(
        method="POST",
        path="/items",
        client_ip="127.0.0.1",
        headers={"Host": "api.example.test"},
        body=b"request",
        target_host="api.example.test",
    )
    recorder.record_response(
        ExchangeResponse(status_code=201, reason="Created", headers={}, body=b"response"),
        request_id=request_id,
        duration_ms=12.0,
        client_ip="127.0.0.1",
        target_host="api.example.test",
    )
    journal.clear()
    bus.shutdown()

    assert journal.list_entries() == ()
    assert [event.event_type for event in store.list_events(request_id=request_id)] == [
        "request.observed",
        "request.body_captured",
        "response.observed",
        "response.body_captured",
        "exchange.completed",
    ]
    store.close()


def test_artifact_history_is_queryable_by_source_request_id(tmp_path) -> None:
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    store.append(
        ArtifactRecorded(
            request_id=42,
            artifact_id="replay-1",
            artifact_type="replay",
            status="applied",
        )
    )

    events = store.list_events(request_id=42)

    assert len(events) == 1
    assert events[0].payload["artifact_id"] == "replay-1"
    store.close()
