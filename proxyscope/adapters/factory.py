from proxyscope.adapters.editing.policy_editor import edit_policy_rule_with_external_editor
from proxyscope.adapters.editing.response_editor import edit_pending_response_with_external_editor
from proxyscope.adapters.replay.requests_adapter import edit_and_resend_logged_request
from proxyscope.adapters.sessions.json_export import export_entries, load_entries_from_json
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.journal import RequestJournal
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.application.services import RuntimeApplicationServices, create_runtime_application_services


def create_default_runtime_application_services(
    *,
    settings: RuntimeSettingsState,
    policies: PolicyAdministrationService,
    configuration: RuntimeConfigurationService,
    request_journal: RequestJournal,
    response_modifier: ResponseModifierService,
    proxy_base_url: str | None,
) -> RuntimeApplicationServices:
    return create_runtime_application_services(
        settings=settings,
        policies=policies,
        configuration=configuration,
        request_journal=request_journal,
        response_modifier=response_modifier,
        proxy_base_url=proxy_base_url,
        policy_editor=edit_policy_rule_with_external_editor,
        replay_request=edit_and_resend_logged_request,
        response_editor=edit_pending_response_with_external_editor,
        export_entries=export_entries,
        load_entries=load_entries_from_json,
    )
