from pathlib import Path
from unittest.mock import Mock

import pytest

from proxyscope.application.artifacts import ArtifactStatus, InMemoryArtifactStore
from proxyscope.application.events import EventBus, ReplayCompleted, ReplayRequested
from proxyscope.application.journal import RequestJournal
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.service_adapters import RuntimeApplicationAdapters
from proxyscope.application.services import create_runtime_application_services
from proxyscope.application.traffic_rules import TrafficRuleAdministrationService
from proxyscope.contracts.traffic_rules import RespondAction, RulePhase, TrafficMatch, TrafficRule
from tests.support.exchanges import recorded_exchange
from tests.support.runtime_context import RuntimeTestContext


@pytest.mark.parametrize("injected_rules", [False, True])
@pytest.mark.parametrize("injected_artifacts", [False, True])
def test_composed_services_share_journal_settings_and_rule_storage(tmp_path, injected_rules, injected_artifacts):
    config = RuntimeTestContext(config_path=tmp_path / "runtime.json")
    journal = RequestJournal()
    journal.replace_entries([recorded_exchange()])
    entry = journal.list_entries()[0]
    adapters = RuntimeApplicationAdapters(
        replay_request=Mock(return_value=(True, "replayed")),
        response_editor=Mock(),
        export_entries=Mock(return_value=Path("session.json")),
        load_entries=Mock(return_value=[]),
    )
    artifacts = InMemoryArtifactStore() if injected_artifacts else None
    rules = (
        TrafficRuleAdministrationService(on_change=config.configuration.set_traffic_rules) if injected_rules else None
    )
    bus = EventBus()
    events = []
    bus.subscribe(events.append)
    services = create_runtime_application_services(
        settings=config.settings_state,
        configuration=config.configuration,
        request_journal=journal,
        response_modifier=ResponseModifierService(),
        proxy_base_url="http://127.0.0.1:8080",
        adapters=adapters,
        event_bus=bus,
        artifact_store=artifacts,
        traffic_rules=rules,
    )
    assert services.requests.list_entries() == [entry]
    services.sessions.session(["load", "empty.json"])
    assert services.requests.list_entries() == []
    adapters.load_entries.assert_called_once_with("empty.json")

    services.settings.add_whitelist_entry("https://API.TEST/items")
    assert config.whitelist_entries() == ("api.test",)
    assert "api.test" in services.runtime_commands.execute("wl show", on_cache_toggle=None).status_message

    rule = TrafficRule("saved", "Saved", True, 0, RulePhase.RESPOND, TrafficMatch(), RespondAction())
    services.traffic_rules.add_rule(rule)
    if rules is not None:
        assert services.traffic_rules is rules
    assert config.config_repository.load(config.config_path).traffic_rules[0]["id"] == "saved"

    assert services.replay.replay(entry) == "replayed"
    adapters.replay_request.assert_called_once_with(
        entry, request_url="http://api.test/items", proxy_base_url="http://127.0.0.1:8080"
    )
    replay_events = [event for event in events if isinstance(event, (ReplayRequested, ReplayCompleted))]
    assert [type(event) for event in replay_events] == [ReplayRequested, ReplayCompleted]
    assert replay_events[0].artifact_id == replay_events[1].artifact_id
    if artifacts is not None:
        assert artifacts.list_for_source(entry.request_id)[0].status is ArtifactStatus.APPLIED
