import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from proxyscope.app.composition import (
    create_mitm_interceptor,
    create_proxy_runtime_context,
    create_runtime_object_graph,
)
from proxyscope.application.journal import RequestJournal
from proxyscope.mitm.certificates import MitmCertificateError
from proxyscope.mitm.tunnel import MitmTLSInterceptor
from tests.support.runtime_context import RuntimeTestContext, processing_dependencies


class TestMitmComposition(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime_context = create_proxy_runtime_context(
            **processing_dependencies(RuntimeTestContext()),
            request_journal=RequestJournal(),
        )

    def test_create_mitm_interceptor_bootstraps_ca_when_enabled(self) -> None:
        fake_ca = Mock()
        fake_ca.ensure_ca_material.return_value = False

        with patch("proxyscope.app.composition.default_ca", return_value=fake_ca):
            interceptor = create_mitm_interceptor(
                runtime_context=self.runtime_context,
                enabled=True,
                ca_root=None,
            )

        self.assertIsInstance(interceptor, MitmTLSInterceptor)
        fake_ca.ensure_ca_material.assert_called_once_with()

    def test_create_mitm_interceptor_returns_none_when_ca_bootstrap_fails(self) -> None:
        fake_ca = Mock()
        fake_ca.ensure_ca_material.side_effect = MitmCertificateError("boom")

        with patch("proxyscope.app.composition.default_ca", return_value=fake_ca):
            with self.assertLogs("pscope.app", level="WARNING") as captured:
                interceptor = create_mitm_interceptor(
                    runtime_context=self.runtime_context,
                    enabled=True,
                    ca_root=None,
                )

        self.assertIsNone(interceptor)
        self.assertIn("MITM disabled: failed to initialize local CA: boom", "\n".join(captured.output))
        fake_ca.ensure_ca_material.assert_called_once_with()

    def test_create_mitm_interceptor_skips_ca_bootstrap_when_disabled(self) -> None:
        with patch("proxyscope.app.composition.default_ca") as default_ca_mock:
            interceptor = create_mitm_interceptor(
                runtime_context=self.runtime_context,
                enabled=False,
                ca_root=None,
            )

        self.assertIsNone(interceptor)
        default_ca_mock.assert_not_called()

    def test_create_mitm_interceptor_uses_configured_ca_root(self) -> None:
        fake_ca = Mock()
        fake_ca.ensure_ca_material.return_value = False

        with patch("proxyscope.app.composition.certificate_authority_for_root", return_value=fake_ca) as ca_factory:
            interceptor = create_mitm_interceptor(
                runtime_context=self.runtime_context,
                enabled=True,
                ca_root="custom-certs",
            )

        self.assertIsInstance(interceptor, MitmTLSInterceptor)
        ca_factory.assert_called_once_with("custom-certs")
        fake_ca.ensure_ca_material.assert_called_once_with()

    def test_create_runtime_object_graph_composes_lifecycle_dependencies(self) -> None:
        server = Mock()
        server.server_address = ("127.0.0.1", 8080)
        server_factory = Mock(return_value=server)

        graph = create_runtime_object_graph(
            host="127.0.0.1",
            port=8080,
            config_path=None,
            mitm_enabled=False,
            certs_dir="custom-certs",
            edit_timeout_s=3.0,
            server_factory=server_factory,
        )

        self.assertIs(graph.server, server)
        self.assertIs(graph.runtime_context.cache_policy, graph.settings)
        self.assertEqual(graph.settings.mitm_certs_dir, Path("custom-certs"))
        self.assertFalse(graph.settings.mitm_enabled)
        server_factory.assert_called_once()
        self.assertIs(server_factory.call_args.kwargs["runtime_context"], graph.runtime_context)
        self.assertIsNone(server_factory.call_args.kwargs["mitm_interceptor"])


if __name__ == "__main__":
    unittest.main()
