from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from proxyscope.adapters.components import CoreCommandsAdapter
from proxyscope.adapters.event_store import SQLiteEventStore
from proxyscope.adapters.events import EventBusAdapter
from proxyscope.adapters.journal import JournalAdapter
from proxyscope.adapters.mitm.certificates import MitmCertificateError, certificate_authority_for_root, default_ca
from proxyscope.adapters.mitm.tunnel import MitmTLSInterceptor
from proxyscope.adapters.proxy.server import ProxyHTTPServer, create_server
from proxyscope.application.artifacts import ArtifactStore, InMemoryArtifactStore
from proxyscope.application.commands import CommandRegistry, create_core_runtime_component
from proxyscope.application.components import ComponentContext, ComponentManager
from proxyscope.application.configuration import (
    ComponentSettings,
    ConfigDocument,
    EventStoreSettings,
    JsonConfigRepository,
    RuntimeConfigurationService,
)
from proxyscope.application.event_store import EventStore, EventStoreWriter, NoopEventStore
from proxyscope.application.events import EventBus
from proxyscope.application.journal import RequestJournal
from proxyscope.application.observability import RequestResponseRecorder, RuntimeEventDispatcher
from proxyscope.application.processing.middleware import CacheInvalidationMiddleware
from proxyscope.application.processing.pipeline import ExchangePipeline
from proxyscope.application.processing.ports import RequestMiddleware, ResponseMiddleware
from proxyscope.application.proxy.runtime import ProxyRuntimeContext
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.application.services import RuntimeApplicationServices
from proxyscope.application.traffic_rules import (
    TrafficRuleAdministrationService,
    TrafficRuleEngine,
    TrafficRuleStore,
    parse_rule,
)
from proxyscope.bootstrap.runtime_services import create_default_runtime_application_services
from proxyscope.components.mockserver import (
    MockServerComponent,
    MockServerService,
    mockserver_configuration_from_payload,
    mockserver_configuration_payload,
)
from proxyscope.contracts.events import RuntimeEvent, RuntimeStateSnapshot, RuntimeStateSnapshotRequested

if TYPE_CHECKING:
    from proxyscope.components.tui import TuiComponent

LOGGER = logging.getLogger("pscope.app")


@dataclass(frozen=True)
class RuntimeObjectGraph:
    settings: RuntimeSettingsState
    configuration: RuntimeConfigurationService
    request_journal: RequestJournal
    response_modifier: ResponseModifierService
    event_bus: EventBus
    event_store: EventStore
    artifact_store: ArtifactStore
    mockserver: MockServerService
    tui: TuiComponent | None
    traffic_rules: TrafficRuleAdministrationService
    runtime_events: RuntimeEventDispatcher
    application_services: RuntimeApplicationServices
    component_manager: ComponentManager
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
    request_shutdown: Callable[[], None] | None = None,
    on_cache_toggle: Callable[[], None] | None = None,
    server_factory: Callable[..., ProxyHTTPServer] = create_server,
) -> RuntimeObjectGraph:
    event_bus = EventBus()
    repository = JsonConfigRepository()
    document = repository.load(Path(config_path)) if config_path else None
    event_store = _create_event_store(document)
    if document is not None and document.event_store.enabled:
        event_bus.subscribe_async(
            EventStoreWriter(event_store), max_queue_size=document.event_store.queue_size
        )
    artifact_store = InMemoryArtifactStore(
        max_body_bytes=4096 if document is None else document.event_store.max_body_bytes
    )
    settings = RuntimeSettingsState(settings=None if document is None else document.settings)
    configuration = RuntimeConfigurationService(
        settings=settings,
        repository=repository,
        path=config_path,
        event_store=EventStoreSettings() if document is None else document.event_store,
        traffic_rules=() if document is None else document.traffic_rules,
        components=ComponentSettings() if document is None else document.components,
    )
    request_journal = RequestJournal()
    component_events = EventBusAdapter(event_bus)
    component_journal = JournalAdapter(request_journal)
    traffic_rule_store = TrafficRuleStore()
    traffic_rules = TrafficRuleAdministrationService(
        traffic_rule_store,
        event_bus=component_events,
        on_change=configuration.set_traffic_rules,
    )
    if document is not None:
        traffic_rules.replace_rules(tuple(parse_rule(value) for value in document.traffic_rules))
    mockserver = MockServerService(
        mockserver_configuration_from_payload(
            None if document is None else document.components.configuration_for("mockserver")
        ),
        event_bus=component_events,
        on_scenarios_change=lambda _scenarios: configuration.set_component_configuration(
            "mockserver", mockserver_configuration_payload(mockserver.store)
        ),
    )
    traffic_rule_engine = TrafficRuleEngine(
        traffic_rule_store,
        event_bus=event_bus,
    )
    command_registry = CommandRegistry()
    component_manager = ComponentManager(
        command_registry=command_registry,
        event_bus=component_events,
        on_status_change=configuration.set_enabled_components,
    )
    if mitm_enabled is not None:
        settings.set_mitm_enabled(mitm_enabled)
    if certs_dir is not None:
        settings.set_mitm_certs_dir(certs_dir)

    response_modifier = ResponseModifierService(
        edit_timeout_s=edit_timeout_s,
        event_bus=event_bus,
        artifact_store=artifact_store,
    )
    runtime_events = RuntimeEventDispatcher(event_bus)
    runtime_context = create_proxy_runtime_context(
        settings=settings,
        request_journal=request_journal,
        response_modifier=response_modifier,
        runtime_events=runtime_events,
        event_bus=event_bus,
        artifact_store=artifact_store,
        component_manager=component_manager,
        traffic_rule_engine=traffic_rule_engine,
    )
    application_services = create_default_runtime_application_services(
        settings=settings,
        configuration=configuration,
        request_journal=request_journal,
        response_modifier=response_modifier,
        proxy_base_url=f"http://{host}:{port}",
        event_bus=event_bus,
        artifact_store=artifact_store,
        traffic_rules=traffic_rules,
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
    mockserver_component = MockServerComponent(mockserver)
    component_manager.register(
        create_core_runtime_component(
            ComponentContext(
                commands=CoreCommandsAdapter(
                    application_services,
                    on_cache_toggle=on_cache_toggle,
                    management_commands=mockserver_component.management_commands(),
                ).commands,
                event_bus=component_events,
                journal=component_journal,
                event_store=event_store,
                component_manager=component_manager,
            ),
            command_registry=command_registry,
            request_shutdown=request_shutdown,
        )
    )
    component_manager.register(
        mockserver_component.contribution(),
        activate=(document is not None and "mockserver" in document.components.enabled_components),
    )
    event_bus.subscribe(
        _runtime_state_snapshot_handler(
            settings=settings,
            mockserver=mockserver,
            event_bus=component_events,
        )
    )
    tui_component = _create_tui_component(
        enabled=document is not None and "tui" in document.components.enabled_components,
        event_bus=component_events,
        journal=component_journal,
    )
    if tui_component is not None:
        component_manager.register(tui_component.contribution())
    return RuntimeObjectGraph(
        settings=settings,
        configuration=configuration,
        request_journal=request_journal,
        response_modifier=response_modifier,
        event_bus=event_bus,
        event_store=event_store,
        artifact_store=artifact_store,
        mockserver=mockserver,
        tui=tui_component,
        traffic_rules=traffic_rules,
        runtime_events=runtime_events,
        application_services=application_services,
        component_manager=component_manager,
        runtime_context=runtime_context,
        server=server,
    )


def _create_tui_component(
    *,
    enabled: bool,
    event_bus: EventBusAdapter,
    journal: JournalAdapter,
) -> TuiComponent | None:
    if not enabled:
        return None
    # Import Textual only when the configuration enables the terminal component.
    from proxyscope.components.tui import TuiComponent

    return TuiComponent(ComponentContext(event_bus=event_bus, journal=journal))


def _runtime_state_snapshot_handler(
    *,
    settings: RuntimeSettingsState,
    mockserver: MockServerService,
    event_bus: EventBusAdapter,
) -> Callable[[RuntimeEvent], None]:
    def handle(event: RuntimeEvent) -> None:
        if not isinstance(event, RuntimeStateSnapshotRequested):
            return
        snapshot = settings.snapshot
        event_bus.publish(
            RuntimeStateSnapshot(
                correlation_id=event.event_id,
                settings={
                    "log_level": logging.getLevelName(snapshot.log_level),
                    "log_whitelist": snapshot.log_whitelist,
                    "cache_invalidation_enabled": snapshot.cache_invalidation_enabled,
                    "mitm_enabled": snapshot.mitm_enabled,
                    "mitm_certs_dir": str(snapshot.mitm_certs_dir),
                },
                mockserver_configuration={"scenarios": mockserver.store.serialize()},
            )
        )

    return handle


def create_proxy_runtime_context(
    *,
    settings: RuntimeSettingsState,
    request_journal: RequestJournal,
    response_modifier: ResponseModifierService | None = None,
    runtime_events: RuntimeEventDispatcher | None = None,
    event_bus: EventBus | None = None,
    artifact_store: ArtifactStore | None = None,
    component_manager: ComponentManager | None = None,
    traffic_rule_engine: TrafficRuleEngine | None = None,
) -> ProxyRuntimeContext:
    resolved_modifier = response_modifier or ResponseModifierService(artifact_store=artifact_store)
    resolved_event_bus = event_bus or EventBus()
    resolved_events = runtime_events or RuntimeEventDispatcher(resolved_event_bus)
    recorder = RequestResponseRecorder(
        settings=settings,
        request_journal=request_journal,
        event_bus=resolved_event_bus,
    )
    pipeline = ExchangePipeline(
        exchange_recorder=recorder,
        response_transformer=resolved_modifier,
        runtime_events=resolved_events,
        cache_middleware=CacheInvalidationMiddleware(settings),
        dynamic_request_middlewares=(
            None
            if component_manager is None
            else lambda: tuple(cast(RequestMiddleware, item) for item in component_manager.request_middlewares())
        ),
        dynamic_response_middlewares=(
            None
            if component_manager is None
            else lambda: tuple(cast(ResponseMiddleware, item) for item in component_manager.response_middlewares())
        ),
        traffic_rule_evaluator=traffic_rule_engine,
    )
    return ProxyRuntimeContext(
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


def _create_event_store(document: ConfigDocument | None) -> EventStore:
    if document is None or not document.event_store.enabled:
        return NoopEventStore()
    settings = document.event_store
    return SQLiteEventStore(
        settings.path,
        max_body_bytes=settings.max_body_bytes,
        max_events=settings.max_events,
        max_age_days=settings.max_age_days,
        max_storage_bytes=settings.max_storage_bytes,
    )
