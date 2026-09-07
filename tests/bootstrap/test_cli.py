import unittest
from argparse import Namespace
from unittest.mock import Mock, patch

from proxyscope.bootstrap.cli import main


class TestAppMain(unittest.TestCase):
    def test_main_builds_options_and_runs_managed_application(self) -> None:
        parser = Mock()
        parser.parse_args.return_value = Namespace(
            host="127.0.0.1",
            port=9090,
            config="runtime.json",
            mitm="off",
            certs_dir="custom-certs",
        )
        application = Mock()
        application.__enter__ = Mock(return_value=application)
        application.__exit__ = Mock(return_value=None)

        with (
            patch("proxyscope.bootstrap.cli._build_parser", return_value=parser),
            patch("proxyscope.bootstrap.cli.ProxyApplication", return_value=application) as application_factory,
        ):
            main()

        options = application_factory.call_args.args[0]
        self.assertEqual(options.host, "127.0.0.1")
        self.assertEqual(options.port, 9090)
        self.assertEqual(options.config_path, "runtime.json")
        self.assertFalse(options.mitm_enabled)
        self.assertEqual(options.certs_dir, "custom-certs")
        application.run.assert_called_once_with()

    def test_main_preserves_unspecified_mitm_setting(self) -> None:
        parser = Mock()
        parser.parse_args.return_value = Namespace(
            host="127.0.0.1",
            port=8080,
            config=None,
            mitm=None,
            certs_dir=None,
        )
        application = Mock()
        application.__enter__ = Mock(return_value=application)
        application.__exit__ = Mock(return_value=None)

        with (
            patch("proxyscope.bootstrap.cli._build_parser", return_value=parser),
            patch("proxyscope.bootstrap.cli.ProxyApplication", return_value=application) as application_factory,
        ):
            main()

        self.assertIsNone(application_factory.call_args.args[0].mitm_enabled)

if __name__ == "__main__":
    unittest.main()
