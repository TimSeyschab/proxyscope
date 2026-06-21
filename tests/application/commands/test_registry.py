import unittest
from types import SimpleNamespace

from proxyscope.application.commands import (
    CommandDefinition,
    CommandExecutionResult,
    CommandRegistry,
    RuntimeCommandExecutionResult,
    create_runtime_command_registry,
)


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

    def test_dispatch_parses_quoted_arguments(self) -> None:
        seen: list[list[str]] = []
        registry = CommandRegistry(
            [
                CommandDefinition(
                    name="demo",
                    usage="demo <value>",
                    help_text="Run demo.",
                    handler=lambda arguments: seen.append(arguments) or CommandExecutionResult("done"),
                )
            ]
        )

        self.assertEqual(registry.dispatch('demo "one two" three'), CommandExecutionResult("done"))
        self.assertEqual(seen, [["one two", "three"]])

    def test_dispatch_reports_invalid_quoted_arguments(self) -> None:
        registry = CommandRegistry(
            [
                CommandDefinition(
                    name="demo",
                    usage="demo <value>",
                    help_text="Run demo.",
                    handler=lambda _arguments: CommandExecutionResult("done"),
                )
            ]
        )

        result = registry.dispatch('demo "unterminated')

        self.assertEqual(result, CommandExecutionResult("Invalid command syntax: No closing quotation"))

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

    def test_runtime_registry_composes_command_groups_in_expected_help_order(self) -> None:
        registry = create_runtime_command_registry(
            _fake_runtime_services(),
            request_shutdown=None,
            on_cache_toggle=None,
            on_schedule_policy_edit=lambda _name: None,
        )

        self.assertEqual(
            registry.build_help_summary(),
            "Commands: help | clear | sites | filter ... | find <text> | export <json|har> <path> | "
            "session <save|load> <path> | loglevel <LEVEL> | mitm ... | whitelist ... | cache ... | "
            "config ... | policy ... | quit",
        )
        self.assertTrue(registry.contains("wl show", command_name="whitelist"))
        self.assertTrue(registry.contains("pol show", command_name="policy"))

    def test_runtime_registry_forwards_tokenized_arguments_to_runtime_commands(self) -> None:
        services = _fake_runtime_services()
        registry = create_runtime_command_registry(
            services,
            request_shutdown=None,
            on_cache_toggle=None,
            on_schedule_policy_edit=lambda _name: None,
        )

        result = registry.dispatch('policy add-static GET https://example.com 200 text/plain "hello quoted body"')

        self.assertEqual(result, CommandExecutionResult("runtime done"))
        self.assertEqual(
            services.runtime_commands.seen_parts,
            ["policy", "add-static", "GET", "https://example.com", "200", "text/plain", "hello quoted body"],
        )


class _FakeRuntimeCommands:
    def __init__(self) -> None:
        self.seen_parts: list[str] = []

    def execute_parts(self, parts: list[str], **_kwargs) -> RuntimeCommandExecutionResult:
        self.seen_parts = parts
        return RuntimeCommandExecutionResult(handled=True, status_message="runtime done")


def _fake_runtime_services():
    return SimpleNamespace(
        requests=SimpleNamespace(
            clear=lambda: "cleared",
            top_sites_summary=lambda: "sites",
            apply_filter=lambda _args: "filtered",
            find=lambda _args: "found",
        ),
        sessions=SimpleNamespace(
            export=lambda _args: "exported",
            session=lambda _args: "session",
        ),
        runtime_commands=_FakeRuntimeCommands(),
    )


if __name__ == "__main__":
    unittest.main()
