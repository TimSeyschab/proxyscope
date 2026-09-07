from dataclasses import dataclass

from proxyscope.application.actions import (
    RuntimeReplayActionService,
    RuntimeResponseEditActionService,
)
from proxyscope.application.artifacts import ArtifactStore, InMemoryArtifactStore
from proxyscope.application.commands.runtime_service import RuntimeCommandService
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.events import EventBus
from proxyscope.application.journal import RequestJournal
from proxyscope.application.requests import RequestApplicationService
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.application.service_adapters import RuntimeApplicationAdapters
from proxyscope.application.sessions import SessionApplicationService
from proxyscope.application.settings import SettingsApplicationService
from proxyscope.application.traffic_rules import TrafficRuleAdministrationService


@dataclass(frozen=True)
class RuntimeApplicationServices:
    requests: RequestApplicationService
    sessions: SessionApplicationService
    settings: SettingsApplicationService
    runtime_commands: RuntimeCommandService
    replay: RuntimeReplayActionService
    response_edits: RuntimeResponseEditActionService
    traffic_rules: TrafficRuleAdministrationService


def create_runtime_application_services(
    *,
    settings: RuntimeSettingsState,
    configuration: RuntimeConfigurationService,
    request_journal: RequestJournal,
    response_modifier: ResponseModifierService,
    proxy_base_url: str | None,
    adapters: RuntimeApplicationAdapters,
    event_bus: EventBus | None = None,
    artifact_store: ArtifactStore | None = None,
    traffic_rules: TrafficRuleAdministrationService | None = None,
) -> RuntimeApplicationServices:
    resolved_artifact_store = artifact_store or InMemoryArtifactStore()
    resolved_traffic_rules = traffic_rules or TrafficRuleAdministrationService(
        event_bus=event_bus,
        on_change=configuration.set_traffic_rules,
    )
    request_service = RequestApplicationService(request_journal)
    return RuntimeApplicationServices(
        requests=request_service,
        sessions=SessionApplicationService(
            request_journal,
            export_entries=adapters.export_entries,
            load_entries=adapters.load_entries,
        ),
        settings=SettingsApplicationService(settings, configuration),
        runtime_commands=RuntimeCommandService(settings=settings, configuration=configuration),
        replay=RuntimeReplayActionService(
            proxy_base_url=proxy_base_url,
            replay_request=adapters.replay_request,
            event_bus=event_bus,
            artifact_store=resolved_artifact_store,
        ),
        response_edits=RuntimeResponseEditActionService(
            response_modifier,
            resolved_traffic_rules,
            configuration,
            response_editor=adapters.response_editor,
            event_bus=event_bus,
        ),
        traffic_rules=resolved_traffic_rules,
    )
