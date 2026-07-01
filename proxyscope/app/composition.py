import logging
from pathlib import Path

from proxyscope.adapters.observability.events import RuntimeEventDispatcher
from proxyscope.adapters.observability.exchange_recorder import RequestResponseRecorder
from proxyscope.application.journal import RequestJournal
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.mitm.certificates import MitmCertificateError, certificate_authority_for_root, default_ca
from proxyscope.mitm.tunnel import MitmTLSInterceptor
from proxyscope.policies.engine import PolicyEngine
from proxyscope.processing.middleware import CacheInvalidationMiddleware
from proxyscope.processing.pipeline import ExchangePipeline
from proxyscope.proxy.runtime import ProxyRuntimeContext

LOGGER = logging.getLogger("pscope.app")


def create_proxy_runtime_context(
    *,
    settings: RuntimeSettingsState,
    policies: PolicyAdministrationService,
    request_journal: RequestJournal,
    response_modifier: ResponseModifierService | None = None,
    runtime_events: RuntimeEventDispatcher | None = None,
) -> ProxyRuntimeContext:
    policy_engine = PolicyEngine(policies.repository)
    resolved_modifier = response_modifier or ResponseModifierService()
    resolved_events = runtime_events or RuntimeEventDispatcher()
    recorder = RequestResponseRecorder(
        settings=settings,
        request_journal=request_journal,
    )
    pipeline = ExchangePipeline(
        policy_evaluator=policy_engine,
        exchange_recorder=recorder,
        response_transformer=resolved_modifier,
        runtime_events=resolved_events,
        cache_middleware=CacheInvalidationMiddleware(settings),
    )
    return ProxyRuntimeContext(
        policy_evaluator=policy_engine,
        exchange_recorder=recorder,
        response_transformer=resolved_modifier,
        runtime_events=resolved_events,
        cache_policy=settings,
        exchange_pipeline=pipeline,
    )


def create_mitm_interceptor(
    *,
    runtime_context: ProxyRuntimeContext,
    enabled: bool,
    ca_root: str | Path | None,
) -> MitmTLSInterceptor | None:
    if not enabled:
        return None

    ca = default_ca() if ca_root is None else certificate_authority_for_root(ca_root)
    try:
        created_new_ca = ca.ensure_ca_material()
        if created_new_ca:
            LOGGER.info(
                "Generated local MITM CA materials cert=%s key=%s",
                ca.ca_cert_path,
                ca.ca_key_path,
            )
        return MitmTLSInterceptor(certificate_authority=ca, runtime_context=runtime_context)
    except MitmCertificateError as exc:
        LOGGER.warning("MITM disabled: failed to initialize local CA: %s", exc)
        return None
