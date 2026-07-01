import logging
import unittest

from proxyscope.adapters.tui.cli import RuntimeCLI
from proxyscope.application.journal import RequestJournal
from tests.support.runtime_context import RuntimeTestContext, runtime_application_services


def _runtime_cli(*, config: RuntimeTestContext | None = None, journal: RequestJournal | None = None) -> RuntimeCLI:
    context = config or RuntimeTestContext()
    return RuntimeCLI(
        application_services=runtime_application_services(
            context,
            request_journal=journal,
        ),
    )


def _status_message(cli: RuntimeCLI) -> str:
    return cli.build_screen_model().status_bar.message


class TestRuntimeCLI(unittest.TestCase):
    def test_execute_help_command_updates_status(self) -> None:
        cli = _runtime_cli()

        should_exit = cli.execute_command("help")

        self.assertFalse(should_exit)
        self.assertIn("filter", _status_message(cli))
        self.assertIn("mitm", _status_message(cli))

    def test_execute_quit_command_requests_shutdown(self) -> None:
        cli = _runtime_cli()
        called = {"shutdown": False}

        def shutdown() -> None:
            called["shutdown"] = True

        cli._shutdown_server = shutdown  # type: ignore[attr-defined]

        should_exit = cli.execute_command("quit")

        self.assertTrue(should_exit)
        self.assertTrue(called["shutdown"])

    def test_warning_log_records_update_status_message(self) -> None:
        cli = _runtime_cli()
        record = logging.LogRecord(
            "pscope.test",
            logging.WARNING,
            __file__,
            1,
            "runtime warning",
            (),
            None,
        )

        cli.emit(record)

        self.assertEqual(_status_message(cli), "runtime warning")

    def test_site_visit_hook_feeds_selected_site_action(self) -> None:
        config = RuntimeTestContext()
        cli = _runtime_cli(config=config)

        cli.on_site_visit("example.com")
        cli.add_selected_site_to_whitelist()

        self.assertEqual(config.whitelist_entries(), ("example.com",))


if __name__ == "__main__":
    unittest.main()
