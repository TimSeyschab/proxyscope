from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.editing.modifier import ResponseModifierService
from proxyscope.app.logging.observability import RuntimeEventDispatcher
from proxyscope.app.logging.request_response import RequestResponseRecorder
from proxyscope.app.runtime.journal import RequestJournal
from proxyscope.policies.engine import PolicyEngine
from proxyscope.processing.middleware import CacheInvalidationMiddleware
from proxyscope.processing.pipeline import ExchangePipeline
from proxyscope.proxy.runtime import ProxyRuntimeContext


def create_proxy_runtime_context(
    *,
    runtime_config: RuntimeConfig,
    request_journal: RequestJournal,
    response_modifier: ResponseModifierService | None = None,
    runtime_events: RuntimeEventDispatcher | None = None,
) -> ProxyRuntimeContext:
    policy_engine = PolicyEngine(runtime_config.policy_repository)
    resolved_modifier = response_modifier or ResponseModifierService()
    resolved_events = runtime_events or RuntimeEventDispatcher()
    recorder = RequestResponseRecorder(
        runtime_config=runtime_config,
        request_journal=request_journal,
    )
    pipeline = ExchangePipeline(
        policy_evaluator=policy_engine,
        exchange_recorder=recorder,
        response_transformer=resolved_modifier,
        runtime_events=resolved_events,
        cache_middleware=CacheInvalidationMiddleware(runtime_config),
    )
    return ProxyRuntimeContext(
        policy_evaluator=policy_engine,
        exchange_recorder=recorder,
        response_transformer=resolved_modifier,
        runtime_events=resolved_events,
        cache_policy=runtime_config,
        exchange_pipeline=pipeline,
    )
