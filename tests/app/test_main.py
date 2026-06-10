import unittest
from argparse import Namespace
from unittest.mock import Mock, patch

from proxyscope.app.main import main


class TestAppMain(unittest.TestCase):
    def test_main_builds_options_and_runs_managed_application(self) -> None:
        parser = Mock()
        parser.parse_args.return_value = Namespace(
            host="127.0.0.1",
            port=9090,
            config="runtime.json",
            mitm="off",
            certs_dir="custom-certs",
            no_ui=False,
        )
        application = Mock()
        application.__enter__ = Mock(return_value=application)
        application.__exit__ = Mock(return_value=None)

        with (
            patch("proxyscope.app.main._build_parser", return_value=parser),
            patch("proxyscope.app.main.ProxyApplication", return_value=application) as application_factory,
            patch("proxyscope.app.main.sys.stdin.isatty", return_value=True),
            patch("proxyscope.app.main.sys.stdout.isatty", return_value=True),
        ):
            main()

        options = application_factory.call_args.args[0]
        self.assertEqual(options.host, "127.0.0.1")
        self.assertEqual(options.port, 9090)
        self.assertEqual(options.config_path, "runtime.json")
        self.assertFalse(options.mitm_enabled)
        self.assertEqual(options.certs_dir, "custom-certs")
        self.assertTrue(options.use_ui)
        application.run.assert_called_once_with()

    def test_main_disables_ui_for_non_tty(self) -> None:
        parser = Mock()
        parser.parse_args.return_value = Namespace(
            host="127.0.0.1",
            port=8080,
            config=None,
            mitm=None,
            certs_dir=None,
            no_ui=False,
        )
        application = Mock()
        application.__enter__ = Mock(return_value=application)
        application.__exit__ = Mock(return_value=None)

        with (
            patch("proxyscope.app.main._build_parser", return_value=parser),
            patch("proxyscope.app.main.ProxyApplication", return_value=application) as application_factory,
            patch("proxyscope.app.main.sys.stdin.isatty", return_value=False),
        ):
            main()

        self.assertFalse(application_factory.call_args.args[0].use_ui)


if __name__ == "__main__":
    unittest.main()
