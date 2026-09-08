from unittest.mock import Mock

import pytest

from proxyscope.application.commands import CommandRegistry, create_core_runtime_component
from proxyscope.application.components import ComponentContext, ComponentContribution, ComponentManager


def core_runtime(*, manager_available=True, shutdown=None):
    registry = CommandRegistry()
    manager = ComponentManager(command_registry=registry)
    manager.register(
        create_core_runtime_component(
            ComponentContext(commands=(), component_manager=manager if manager_available else None),
            command_registry=registry,
            request_shutdown=shutdown,
        )
    )
    return registry, manager


@pytest.mark.parametrize("has_callback", [False, True])
@pytest.mark.parametrize("command", ["quit", "exit", "q"])
def test_quit_aliases_request_shutdown(command, has_callback):
    callback = Mock() if has_callback else None
    registry, _ = core_runtime(shutdown=callback)
    result = registry.dispatch(command)
    assert result.should_exit
    assert result.status_message == "Shutting down server..."
    if callback is not None:
        callback.assert_called_once_with()


def test_component_commands_follow_lifecycle_and_handle_missing_components():
    registry, manager = core_runtime()
    manager.register(ComponentContribution("demo", "Demo"), activate=False)
    assert "demo (disabled)" in registry.dispatch("component list").status_message
    assert registry.dispatch("component enable demo").status_message == "Component enabled: demo"
    assert manager.is_active("demo")
    assert "demo (active)" in registry.dispatch("component describe demo").status_message
    assert registry.dispatch("component disable demo").status_message == "Component disabled: demo"
    assert not manager.is_active("demo")
    assert "Component not found" in registry.dispatch("component describe missing").status_message
    assert "not registered" in registry.dispatch("component enable missing").status_message
    assert "cannot be disabled" in registry.dispatch("component disable core").status_message
    assert "Components:" in registry.dispatch("component").status_message


@pytest.mark.parametrize("command", ["component enable", "component unknown demo", "component disable demo extra"])
def test_invalid_component_commands_report_usage(command):
    registry, _ = core_runtime()
    assert registry.dispatch(command).status_message.startswith("Usage: component")


def test_component_command_without_manager_reports_unavailability():
    registry, _ = core_runtime(manager_available=False)
    assert registry.dispatch("component").status_message == "Component manager is unavailable."
