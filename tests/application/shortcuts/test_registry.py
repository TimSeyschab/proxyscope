import unittest

from proxyscope.application.shortcuts import ShortcutDefinition, ShortcutRegistry


class TestShortcutRegistry(unittest.TestCase):
    def test_registers_global_shortcut(self) -> None:
        registry = ShortcutRegistry()
        shortcut = ShortcutDefinition("shift+k", "Demo", "demo")

        registry.register("demo", shortcut)

        self.assertEqual(registry.resolve("shift+k"), shortcut)

    def test_unregister_component_removes_all_shortcuts(self) -> None:
        registry = ShortcutRegistry()
        registry.register_component(
            "demo",
            (
                ShortcutDefinition("shift+k", "First", "one"),
                ShortcutDefinition("shift+l", "Second", "two"),
            ),
        )

        registry.unregister_component("demo")

        self.assertIsNone(registry.resolve("shift+k"))
        self.assertIsNone(registry.resolve("shift+l"))

    def test_rejects_global_key_collision(self) -> None:
        registry = ShortcutRegistry()
        registry.register("first", ShortcutDefinition("shift+k", "First", "one"))

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register("second", ShortcutDefinition("shift+k", "Second", "two"))

    def test_rejects_key_collision_regardless_of_priority(self) -> None:
        registry = ShortcutRegistry()
        global_shortcut = ShortcutDefinition("shift+k", "Global", "global", priority=0)
        preferred_shortcut = ShortcutDefinition("shift+k", "Preferred", "preferred", priority=1)
        registry.register("core", global_shortcut)

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register("rules", preferred_shortcut)

    def test_rejects_reserved_system_shortcuts(self) -> None:
        registry = ShortcutRegistry()

        for key in (":", "esc", "tab", "shift+tab"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "reserved"):
                registry.register("demo", ShortcutDefinition(key, "Reserved", "demo"))

    def test_returns_none_for_unknown_key(self) -> None:
        self.assertIsNone(ShortcutRegistry().resolve("shift+k"))

    def test_help_text_excludes_unregistered_shortcuts(self) -> None:
        registry = ShortcutRegistry()
        registry.register("demo", ShortcutDefinition("shift+k", "Demo", "demo"))
        registry.unregister_component("demo")

        self.assertNotIn("shift+k", registry.build_help_text())


if __name__ == "__main__":
    unittest.main()
