from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from proxyscope.application.actions.runtime_actions import RuntimeReplayActionService, entry_to_url
from proxyscope.application.artifacts import ArtifactStatus, InMemoryArtifactStore
from proxyscope.application.events import EventBus, ReplayCompleted, ReplayRequested
from tests.support.exchanges import recorded_exchange


@pytest.mark.parametrize(
    "host,port,protocol,path,expected",
    [
        (None, 80, "http", "/", None),
        ("api.test", None, "http", "items", "http://api.test/items"),
        ("api.test", 80, "http", "/items", "http://api.test/items"),
        ("api.test", 443, "https-mitm", "/items", "https://api.test/items"),
        ("api.test", 8443, "https", "/items", "https://api.test:8443/items"),
        ("api.test", 80, "http", "https://other.test/path", "https://other.test/path"),
    ],
)
def test_replay_url_preserves_target(host, port, protocol, path, expected):
    assert entry_to_url(recorded_exchange(host=host, port=port, protocol=protocol, path=path)) == expected


@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize("with_bus", [False, True])
def test_replay_records_terminal_status_and_restores_ui(success, with_bus):
    store = InMemoryArtifactStore()
    bus = EventBus() if with_bus else None
    events = []
    if bus is not None:
        bus.subscribe(events.append)
    calls = []

    @contextmanager
    def suspend():
        calls.append("suspend")
        try:
            yield
        finally:
            calls.append("resume")

    service = RuntimeReplayActionService(
        proxy_base_url=None,
        replay_request=Mock(return_value=(success, "result")),
        event_bus=bus,
        artifact_store=store,
    )
    entry = recorded_exchange()
    assert service.replay(entry, suspend_ui=suspend) == "result"
    (artifact,) = store.list_for_source(entry.request_id)
    assert artifact.status is (ArtifactStatus.APPLIED if success else ArtifactStatus.FAILED)
    assert artifact.error == (None if success else "result")
    assert calls == ["suspend", "resume"]
    if with_bus:
        assert [type(event) for event in events] == [ReplayRequested, ReplayCompleted]
        assert events[-1].success is success


def test_replay_adapter_exception_marks_artifact_failed():
    store = InMemoryArtifactStore()
    service = RuntimeReplayActionService(
        proxy_base_url=None, replay_request=Mock(side_effect=OSError("offline")), artifact_store=store
    )
    entry = recorded_exchange()
    assert service.replay(entry) == "Replay failed (offline)."
    (artifact,) = store.list_for_source(entry.request_id)
    assert artifact.status is ArtifactStatus.FAILED
    assert artifact.error == "offline"


def test_missing_target_never_invokes_replay_adapter():
    adapter = Mock()
    service = RuntimeReplayActionService(proxy_base_url=None, replay_request=adapter)
    assert service.replay(recorded_exchange(host=None)) == "Cannot build URL from selected request."
    adapter.assert_not_called()
