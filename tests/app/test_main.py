from argparse import Namespace
import logging
import unittest
from unittest.mock import Mock, patch

from proxyscope.app.main import main
from proxyscope.app.config.runtime import RuntimeConfig, set_runtime_config
from proxyscope.app.runtime.journal import RequestJournal, set_request_journal
from proxyscope.app.editing.modifier import ResponseModifierService, set_response_modifier


class _FakeThread:
    def __init__(self, *, target: Mock, daemon: bool) -> None:
        self._target = target
        self.daemon = daemon
        self.started = False
        self.joined = False

    def start(self) -> None:
        self.started = True

    def join(self, timeout: float | None = None) -> None:
        self.joined = True


class TestAppMain(unittest.TestCase):
    def setUp(self) -> None:
        logging.getLogger().handlers.clear()

    def tearDown(self) -> None:
        logging.getLogger().handlers.clear()
        set_runtime_config(RuntimeConfig())
        set_request_journal(RequestJournal())
        set_response_modifier(ResponseModifierService())

    def test_main_runs_without_ui_when_disabled(self) -> None:
        args = Namespace(
            host="127.0.0.1",
            port=8080,
            config=None,
            mitm=None,
            certs_dir=None,
            no_ui=True,
        )
        parser = Mock()
        parser.parse_args.return_value = args

        server = Mock()
        response_modifier = Mock()

        with (
            patch("proxyscope.app.main._build_parser", return_value=parser),
            patch("proxyscope.app.main.create_server", return_value=server),
            patch("proxyscope.app.main.ResponseModifierService", return_value=response_modifier),
            patch("proxyscope.app.main.configure_logging"),
        ):
            main()

        response_modifier.set_interactive_enabled.assert_called_once_with(False)
        server.serve_forever.assert_called_once_with()
        server.server_close.assert_called_once_with()

    def test_main_runs_ui_mode_and_cleans_up(self) -> None:
        args = Namespace(
            host="127.0.0.1",
            port=8080,
            config=None,
            mitm=None,
            certs_dir=None,
            no_ui=False,
        )
        parser = Mock()
        parser.parse_args.return_value = args

        server = Mock()
        server.close_all_active_tunnels.return_value = 2
        response_modifier = Mock()
        runtime_ui = Mock(level=logging.NOTSET)

        with (
            patch("proxyscope.app.main._build_parser", return_value=parser),
            patch("proxyscope.app.main.create_server", return_value=server),
            patch("proxyscope.app.main.ResponseModifierService", return_value=response_modifier),
            patch("proxyscope.app.main.RuntimeCLI", return_value=runtime_ui),
            patch("proxyscope.app.main.configure_logging"),
            patch("proxyscope.app.main.sys.stdin.isatty", return_value=True),
            patch("proxyscope.app.main.sys.stdout.isatty", return_value=True),
            patch("proxyscope.app.main.set_runtime_observer") as observer_mock,
            patch("proxyscope.app.main.threading.Thread", side_effect=lambda target, daemon: _FakeThread(target=target, daemon=daemon)),
        ):
            main()

        response_modifier.set_interactive_enabled.assert_called_once_with(True)
        runtime_ui.run.assert_called_once()
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        observer_mock.assert_any_call(runtime_ui)
        observer_mock.assert_called_with(None)

    def test_main_applies_mitm_cli_overrides(self) -> None:
        args = Namespace(
            host="127.0.0.1",
            port=8080,
            config=None,
            mitm="off",
            certs_dir="custom-certs",
            no_ui=True,
        )
        parser = Mock()
        parser.parse_args.return_value = args

        server = Mock()
        response_modifier = Mock()

        with (
            patch("proxyscope.app.main._build_parser", return_value=parser),
            patch("proxyscope.app.main.create_server", return_value=server) as create_server_mock,
            patch("proxyscope.app.main.ResponseModifierService", return_value=response_modifier),
            patch("proxyscope.app.main.configure_logging"),
        ):
            main()

        _, kwargs = create_server_mock.call_args
        self.assertFalse(kwargs["auto_enable_mitm"])
        self.assertEqual(str(kwargs["ca_root"]), "custom-certs")
