from collections.abc import Callable

from proxyscope.adapters.components import CoreCommandsAdapter
from proxyscope.application.commands import CommandRegistry, create_core_runtime_component
from proxyscope.application.components import ComponentContext, ComponentManager
from proxyscope.application.services import RuntimeApplicationServices


def core_component_manager(
    services: RuntimeApplicationServices,
    *,
    request_shutdown: Callable[[], None] | None = None,
    on_cache_toggle: Callable[[], None] | None = None,
) -> ComponentManager:
    registry = CommandRegistry()
    manager = ComponentManager(command_registry=registry)
    manager.register(
        create_core_runtime_component(
            ComponentContext(
                commands=CoreCommandsAdapter(services, on_cache_toggle=on_cache_toggle).commands,
                component_manager=manager,
            ),
            command_registry=registry,
            request_shutdown=request_shutdown,
        )
    )
    return manager


def core_command_registry(
    services: RuntimeApplicationServices,
    *,
    request_shutdown: Callable[[], None] | None = None,
    on_cache_toggle: Callable[[], None] | None = None,
) -> CommandRegistry:
    return core_component_manager(
        services,
        request_shutdown=request_shutdown,
        on_cache_toggle=on_cache_toggle,
    ).command_registry
