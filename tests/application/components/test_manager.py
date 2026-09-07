import unittest

from proxyscope.application.commands import CommandDefinition, CommandExecutionResult, CommandRegistry
from proxyscope.application.components import ComponentContribution, ComponentManager, ComponentRegistry
from proxyscope.application.events import ComponentDisabled, ComponentEnabled, EventBus
from proxyscope.application.shortcuts import ShortcutDefinition


class TestComponentContribution(unittest.TestCase):
    def test_rejects_empty_component_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "component_id"):
            ComponentContribution(component_id="", display_name="Demo")

    def test_rejects_non_normalized_component_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "normalized"):
            ComponentContribution(component_id="Demo", display_name="Demo")

    def test_rejects_empty_display_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "display_name"):
            ComponentContribution(component_id="demo", display_name=" ")


class TestComponentRegistry(unittest.TestCase):
    def test_rejects_duplicate_components(self) -> None:
        registry = ComponentRegistry()
        contribution = ComponentContribution(component_id="demo", display_name="Demo")
        registry.register(contribution)

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(contribution)


class TestComponentManager(unittest.TestCase):
    def test_registers_and_deregisters_component_commands(self) -> None:
        manager = ComponentManager()
        contribution = ComponentContribution(
            component_id="demo",
            display_name="Demo",
            commands=(
                CommandDefinition(
                    name="demo",
                    aliases=("d",),
                    help_text="Run demo.",
                    handler=lambda _arguments: CommandExecutionResult("done"),
                ),
            ),
        )

        manager.register(contribution)

        self.assertTrue(manager.is_active("demo"))
        self.assertEqual(manager.command_registry.dispatch("d"), CommandExecutionResult("done"))

        manager.unregister("demo")

        self.assertFalse(manager.is_active("demo"))
        self.assertIsNone(manager.command_registry.dispatch("demo"))
        self.assertNotIn("demo", manager.command_registry.build_help_text())

    def test_rolls_back_component_when_command_registration_fails(self) -> None:
        command_registry = CommandRegistry(
            [
                CommandDefinition(
                    name="existing",
                    help_text="Existing.",
                    handler=lambda _arguments: CommandExecutionResult(),
                )
            ]
        )
        component_registry = ComponentRegistry()
        manager = ComponentManager(component_registry=component_registry, command_registry=command_registry)

        with self.assertRaisesRegex(ValueError, "already registered"):
            manager.register(
                ComponentContribution(
                    component_id="demo",
                    display_name="Demo",
                    commands=(
                        CommandDefinition(
                            name="demo",
                            help_text="Run demo.",
                            handler=lambda _arguments: CommandExecutionResult("demo"),
                        ),
                        CommandDefinition(
                            name="existing",
                            help_text="Duplicate.",
                            handler=lambda _arguments: CommandExecutionResult("duplicate"),
                        ),
                    ),
                )
            )

        self.assertFalse(manager.is_active("demo"))
        self.assertIsNone(component_registry.get("demo"))
        self.assertIsNone(command_registry.dispatch("demo"))
        self.assertEqual(command_registry.dispatch("existing"), CommandExecutionResult())

    def test_rejects_reserved_command_from_non_core_component(self) -> None:
        manager = ComponentManager()

        with self.assertRaisesRegex(ValueError, "reserved"):
            manager.register(
                ComponentContribution(
                    component_id="demo",
                    display_name="Demo",
                    commands=(
                        CommandDefinition(
                            name="quit",
                            help_text="Attempt to override shutdown.",
                            handler=lambda _arguments: CommandExecutionResult(),
                        ),
                    ),
                )
            )

    def test_unregister_removes_component_shortcuts(self) -> None:
        manager = ComponentManager()
        manager.register(
            ComponentContribution(
                component_id="demo",
                display_name="Demo",
                shortcuts=(ShortcutDefinition("shift+k", "Demo", "demo"),),
            )
        )

        manager.unregister("demo")

        self.assertIsNone(manager.shortcut_registry.resolve("shift+k"))

    def test_activation_and_deactivation_publish_component_events(self) -> None:
        events: list[object] = []
        bus = EventBus()
        bus.subscribe(events.append)
        manager = ComponentManager(event_bus=bus)

        manager.register(ComponentContribution(component_id="demo", display_name="Demo"))
        manager.deactivate("demo")

        self.assertIsInstance(events[0], ComponentEnabled)
        self.assertIsInstance(events[1], ComponentDisabled)

    def test_lifecycle_hooks_follow_component_activation(self) -> None:
        calls: list[str] = []
        manager = ComponentManager()
        manager.register(
            ComponentContribution(
                component_id="demo",
                display_name="Demo",
                on_activate=lambda: calls.append("activate"),
                on_deactivate=lambda: calls.append("deactivate"),
            )
        )

        manager.deactivate("demo")

        self.assertEqual(calls, ["activate", "deactivate"])


if __name__ == "__main__":
    unittest.main()
