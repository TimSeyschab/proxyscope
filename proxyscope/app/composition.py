import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from proxyscope.adapters.factory import create_default_runtime_application_services
from proxyscope.adapters.observability.events import RuntimeEventDispatcher
from proxyscope.adapters.observability.exchange_recorder import RequestResponseRecorder
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.journal import RequestJournal
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.application.services import RuntimeApplicationServices
from proxyscope.config.repository import JsonConfigRepository
from proxyscope.mitm.certificates import MitmCertificateError, certificate_authority_for_root, default_ca
from proxyscope.mitm.tunnel import MitmTLSInterceptor
from proxyscope.policies.engine import PolicyEngine
from proxyscope.processing.middleware import CacheInvalidationMiddleware
from proxyscope.processing.pipeline import ExchangePipeline
from proxyscope.proxy.runtime import ProxyRuntimeContext
from proxyscope.proxy.server import ProxyHTTPServer, create_server

LOGGER = logging.getLogger("pscope.app")


@dataclass(frozen=True)
class RuntimeObjectGraph:
    settings: RuntimeSettingsState
    policies: PolicyAdministrationService
    configuration: RuntimeConfigurationService
    request_journal: RequestJournal
    response_modifier: ResponseModifierService
    runtime_events: RuntimeEventDispatcher
    application_services: RuntimeApplicationServices
    runtime_context: ProxyRuntimeContext
    server: ProxyHTTPServer


def create_runtime_object_graph(
    *,
    host: str,
    port: int,
    config_path: str | Path | None,
    mitm_enabled: bool | None,
    certs_dir: str | Path | None,
    edit_timeout_s: float,
    server_factory: Callable[..., ProxyHTTPServer] = create_server,
) -> RuntimeObjectGraph:
    repository = JsonConfigRepository()
    document = repository.load(Path(config_path)) if config_path else None
    settings = RuntimeSettingsState(settings=None if document is None else document.settings)
    policies = PolicyAdministrationService(rules=() if document is None else document.policies)
    configuration = RuntimeConfigurationService(
        settings=settings,
        policies=policies,
        repository=repository,
        path=config_path,
    )
    if mitm_enabled is not None:
        settings.set_mitm_enabled(mitm_enabled)
    if certs_dir is not None:
        settings.set_mitm_certs_dir(certs_dir)

    request_journal = RequestJournal()
    response_modifier = ResponseModifierService(edit_timeout_s=edit_timeout_s)
    runtime_events = RuntimeEventDispatcher()
    runtime_context = create_proxy_runtime_context(
        settings=settings,
        policies=policies,
        request_journal=request_journal,
        response_modifier=response_modifier,
        runtime_events=runtime_events,
    )
    application_services = create_default_runtime_application_services(
        settings=settings,
        policies=policies,
        configuration=configuration,
        request_journal=request_journal,
        response_modifier=response_modifier,
        proxy_base_url=f"http://{host}:{port}",
    )
    server = server_factory(
        host,
        port,
        runtime_context=runtime_context,
        mitm_interceptor=create_mitm_interceptor(
            runtime_context=runtime_context,
            enabled=settings.mitm_enabled,
            ca_root=settings.mitm_certs_dir,
        ),
    )
    return RuntimeObjectGraph(
        settings=settings,
        policies=policies,
        configuration=configuration,
        request_journal=request_journal,
        response_modifier=response_modifier,
        runtime_events=runtime_events,
        application_services=application_services,
        runtime_context=runtime_context,
        server=server,
    )


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
