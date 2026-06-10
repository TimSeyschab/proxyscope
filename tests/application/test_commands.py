import unittest

from proxyscope.application.commands import CommandDefinition, CommandExecutionResult, CommandRegistry


class TestCommandRegistry(unittest.TestCase):
    def test_dispatches_names_and_aliases_without_central_dispatch_chain(self) -> None:
        seen: list[list[str]] = []
        registry = CommandRegistry(
            [
                CommandDefinition(
                    name="demo",
                    aliases=("d",),
                    usage="demo <value>",
                    help_text="Run demo.",
                    handler=lambda arguments: seen.append(arguments) or CommandExecutionResult("done"),
                )
            ]
        )

        self.assertEqual(registry.dispatch("d one two"), CommandExecutionResult("done"))
        self.assertEqual(seen, [["one", "two"]])
        self.assertTrue(registry.contains("demo", command_name="demo"))

    def test_help_is_generated_from_registered_commands(self) -> None:
        registry = CommandRegistry(
            [
                CommandDefinition(
                    name="demo",
                    aliases=("d",),
                    usage="demo <value>",
                    help_text="Run demo.",
                    handler=lambda _arguments: CommandExecutionResult(),
                )
            ]
        )

        self.assertEqual(registry.build_help_summary(), "Commands: demo <value>")
        self.assertIn("demo <value>", registry.build_help_text())
        self.assertIn("Run demo.", registry.build_help_text())

    def test_rejects_duplicate_aliases(self) -> None:
        registry = CommandRegistry(
            [CommandDefinition("one", lambda _arguments: CommandExecutionResult(), "One", aliases=("x",))]
        )

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(
                CommandDefinition("two", lambda _arguments: CommandExecutionResult(), "Two", aliases=("x",))
            )


if __name__ == "__main__":
    unittest.main()
