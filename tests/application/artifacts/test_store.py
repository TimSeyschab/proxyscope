from dataclasses import replace

from proxyscope.application.actions import RuntimeReplayActionService
from proxyscope.application.artifacts import ArtifactStatus, InMemoryArtifactStore, ReplayArtifact
from proxyscope.application.events import EventBus, ReplayCompleted, ReplayRequested
from proxyscope.application.journal import LoggedExchange, LoggedRequestMessage


def _entry(*, host: str | None = "example.test") -> LoggedExchange:
    return LoggedExchange(
        request_id=9,
        started_at=0.0,
        finished_at=None,
        duration_ms=None,
        client_ip="127.0.0.1",
        target_host=host,
        target_port=443,
        protocol="https-mitm",
        request=LoggedRequestMessage("POST", "/items", "POST /items", (("X-Test", "yes"),), "", b"abcdef"),
        response=None,
    )


def test_replay_artifact_is_immutable_and_keeps_limited_body_preview() -> None:
    store = InMemoryArtifactStore(max_body_bytes=3)
    artifact = ReplayArtifact(
        source_request_id=9,
        method="POST",
        url="https://example.test/items",
        headers=(("X-Test", "yes"),),
        body=store.body_reference(b"abcdef"),
    )
    store.add(artifact)

    stored = store.list_for_source(9)[0]

    assert stored.body.preview == b"abc"
    assert stored.body.size == 6
    assert stored.body.truncated
    assert replace(stored, status=ArtifactStatus.RUNNING) != stored


def test_replay_creates_artifact_and_events_for_failure() -> None:
    store = InMemoryArtifactStore(max_body_bytes=4)
    events = []
    bus = EventBus()
    bus.subscribe(events.append)
    replay = RuntimeReplayActionService(
        proxy_base_url=None,
        replay_request=lambda *_args, **_kwargs: (False, "upstream unavailable"),
        event_bus=bus,
        artifact_store=store,
    )

    assert replay.replay(_entry()) == "upstream unavailable"

    artifact = store.list_for_source(9)[0]
    assert artifact.status is ArtifactStatus.FAILED
    assert artifact.error == "upstream unavailable"
    assert artifact.body.preview == b"abcd"
    requested = next(event for event in events if isinstance(event, ReplayRequested))
    completed = next(event for event in events if isinstance(event, ReplayCompleted))
    assert requested.artifact_id == artifact.replay_id
    assert completed.artifact_id == artifact.replay_id
    assert completed.error == "upstream unavailable"


def test_replay_with_missing_host_does_not_create_artifact() -> None:
    store = InMemoryArtifactStore()
    replay = RuntimeReplayActionService(
        proxy_base_url=None,
        replay_request=lambda *_args, **_kwargs: (True, "unused"),
        artifact_store=store,
    )

    assert replay.replay(_entry(host=None)) == "Cannot build URL from selected request."
    assert store.list_for_source(9) == ()
