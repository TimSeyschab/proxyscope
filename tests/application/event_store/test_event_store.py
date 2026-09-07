from datetime import UTC, datetime

from proxyscope.application.event_store import NoopEventStore
from proxyscope.application.events import RequestObserved


def test_noop_event_store_discards_events() -> None:
    store = NoopEventStore()

    store.append(
        RequestObserved(
            request_id=1,
            method="GET",
            path="/health",
            target_host="example.test",
            target_port=443,
            protocol="https",
        )
    )

    assert store.list_events() == ()
    assert store.list_events(request_id=1, occurred_after=datetime.now(UTC)) == ()
    store.close()
