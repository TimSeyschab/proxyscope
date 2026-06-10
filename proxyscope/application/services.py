from dataclasses import dataclass

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.editing.modifier import ResponseModifierService
from proxyscope.app.runtime.journal import RequestJournal
from proxyscope.application.actions import RuntimeReplayActionService, RuntimeResponseEditActionService
from proxyscope.application.policies import PolicyApplicationService
from proxyscope.application.requests import RequestApplicationService
from proxyscope.application.runtime_commands import RuntimeCommandService
from proxyscope.application.sessions import SessionApplicationService
from proxyscope.application.settings import SettingsApplicationService


@dataclass(frozen=True)
class RuntimeApplicationServices:
    requests: RequestApplicationService
    policies: PolicyApplicationService
    sessions: SessionApplicationService
    settings: SettingsApplicationService
    runtime_commands: RuntimeCommandService
    replay: RuntimeReplayActionService
    response_edits: RuntimeResponseEditActionService


def create_runtime_application_services(
    *,
    runtime_config: RuntimeConfig,
    request_journal: RequestJournal,
    response_modifier: ResponseModifierService,
    proxy_base_url: str | None,
) -> RuntimeApplicationServices:
    return RuntimeApplicationServices(
        requests=RequestApplicationService(request_journal),
        policies=PolicyApplicationService(runtime_config),
        sessions=SessionApplicationService(request_journal),
        settings=SettingsApplicationService(runtime_config),
        runtime_commands=RuntimeCommandService(runtime_config=runtime_config),
        replay=RuntimeReplayActionService(proxy_base_url=proxy_base_url),
        response_edits=RuntimeResponseEditActionService(response_modifier, runtime_config),
    )
