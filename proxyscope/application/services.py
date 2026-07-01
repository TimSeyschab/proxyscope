from dataclasses import dataclass

from proxyscope.application.actions import (
    PolicyEditor,
    ReplayRequest,
    ResponseEditor,
    RuntimeReplayActionService,
    RuntimeResponseEditActionService,
)
from proxyscope.application.commands.runtime_service import RuntimeCommandService
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.journal import RequestJournal
from proxyscope.application.policies import PolicyApplicationService
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.requests import RequestApplicationService
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.application.runtime_view import RuntimeViewApplicationService
from proxyscope.application.sessions import ExportEntries, LoadEntries, SessionApplicationService
from proxyscope.application.settings import SettingsApplicationService


@dataclass(frozen=True)
class RuntimeApplicationServices:
    requests: RequestApplicationService
    policies: PolicyApplicationService
    sessions: SessionApplicationService
    settings: SettingsApplicationService
    runtime_view: RuntimeViewApplicationService
    runtime_commands: RuntimeCommandService
    replay: RuntimeReplayActionService
    response_edits: RuntimeResponseEditActionService


def create_runtime_application_services(
    *,
    settings: RuntimeSettingsState,
    policies: PolicyAdministrationService,
    configuration: RuntimeConfigurationService,
    request_journal: RequestJournal,
    response_modifier: ResponseModifierService,
    proxy_base_url: str | None,
    policy_editor: PolicyEditor,
    replay_request: ReplayRequest,
    response_editor: ResponseEditor,
    export_entries: ExportEntries,
    load_entries: LoadEntries,
) -> RuntimeApplicationServices:
    request_service = RequestApplicationService(request_journal)
    policy_service = PolicyApplicationService(policies, configuration, policy_editor=policy_editor)
    return RuntimeApplicationServices(
        requests=request_service,
        policies=policy_service,
        sessions=SessionApplicationService(
            request_journal,
            export_entries=export_entries,
            load_entries=load_entries,
        ),
        settings=SettingsApplicationService(settings, configuration),
        runtime_view=RuntimeViewApplicationService(
            settings=settings,
            policies=policies,
            configuration=configuration,
            requests=request_service,
        ),
        runtime_commands=RuntimeCommandService(settings=settings, policies=policies, configuration=configuration),
        replay=RuntimeReplayActionService(proxy_base_url=proxy_base_url, replay_request=replay_request),
        response_edits=RuntimeResponseEditActionService(
            response_modifier,
            policies,
            configuration,
            response_editor=response_editor,
        ),
    )
