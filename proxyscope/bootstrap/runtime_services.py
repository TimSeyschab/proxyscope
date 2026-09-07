from proxyscope.adapters.editing.response_editor import edit_pending_response_with_external_editor
from proxyscope.adapters.replay.requests_adapter import edit_and_resend_logged_request
from proxyscope.adapters.sessions.json_export import export_entries, load_entries_from_json
from proxyscope.application.artifacts import ArtifactStore
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.events import EventBus
from proxyscope.application.journal import RequestJournal
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.application.services import (
    RuntimeApplicationAdapters,
    RuntimeApplicationServices,
    create_runtime_application_services,
)
from proxyscope.application.traffic_rules import TrafficRuleAdministrationService


def create_default_runtime_application_services(
    *,
    settings: RuntimeSettingsState,
    configuration: RuntimeConfigurationService,
    request_journal: RequestJournal,
    response_modifier: ResponseModifierService,
    proxy_base_url: str | None,
    event_bus: EventBus | None = None,
    artifact_store: ArtifactStore | None = None,
    traffic_rules: TrafficRuleAdministrationService | None = None,
) -> RuntimeApplicationServices:
    return create_runtime_application_services(
        settings=settings,
        configuration=configuration,
        request_journal=request_journal,
        response_modifier=response_modifier,
        proxy_base_url=proxy_base_url,
        event_bus=event_bus,
        artifact_store=artifact_store,
        traffic_rules=traffic_rules,
        adapters=RuntimeApplicationAdapters(
            replay_request=edit_and_resend_logged_request,
            response_editor=edit_pending_response_with_external_editor,
            export_entries=export_entries,
            load_entries=load_entries_from_json,
        ),
    )
