from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.editing.modifier import ResponseModifierService
from proxyscope.app.logging.observability import RuntimeEventDispatcher
from proxyscope.app.logging.request_response import RequestResponseRecorder
from proxyscope.app.runtime.journal import RequestJournal
from proxyscope.proxy.runtime import ProxyRuntimeContext


def create_proxy_runtime_context(
    *,
    runtime_config: RuntimeConfig,
    request_journal: RequestJournal,
    response_modifier: ResponseModifierService | None = None,
    runtime_events: RuntimeEventDispatcher | None = None,
) -> ProxyRuntimeContext:
    resolved_modifier = response_modifier or ResponseModifierService(policy_evaluator=runtime_config)
    resolved_events = runtime_events or RuntimeEventDispatcher()
    return ProxyRuntimeContext(
        policy_evaluator=runtime_config,
        exchange_recorder=RequestResponseRecorder(
            runtime_config=runtime_config,
            request_journal=request_journal,
        ),
        response_transformer=resolved_modifier,
        runtime_events=resolved_events,
        cache_policy=runtime_config,
    )
