import http.client
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from proxyscope.adapters.proxy.server import create_server
from proxyscope.application.configuration import (
    ComponentSettings,
    ConfigDocument,
    JsonConfigRepository,
    RuntimeSettings,
)
from proxyscope.application.processing.models import ExchangeResponse
from proxyscope.application.processing.ports import ForwardRequest
from proxyscope.bootstrap.composition import create_runtime_object_graph
from proxyscope.bootstrap.lifecycle import ApplicationOptions, ProxyApplication
from proxyscope.components.mockserver import (
    MockResponse,
    MockScenario,
    MockScenarioStore,
    mockserver_configuration_payload,
)


class _StaticForwarder:
    def forward(self, request: ForwardRequest) -> ExchangeResponse:
        return ExchangeResponse(200, "OK", {"Content-Length": "2"}, b"ok")


class _FakeServer:
    def __init__(self) -> None:
        self.server_address = ("127.0.0.1", 8080)
        self._stop = threading.Event()
        self.shutdown_calls = 0
        self.close_calls = 0
        self.tunnel_close_calls = 0

    def serve_forever(self) -> None:
        self._stop.wait(timeout=2)

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self._stop.set()

    def server_close(self) -> None:
        self.close_calls += 1

    def close_all_active_tunnels(self) -> int:
        self.tunnel_close_calls += 1
        return 0


class TestProxyApplicationLifecycle(unittest.TestCase):
    def test_composition_root_activates_core_component_commands(self) -> None:
        graph = create_runtime_object_graph(
            host="127.0.0.1",
            port=8080,
            config_path=None,
            mitm_enabled=False,
            certs_dir=None,
            edit_timeout_s=1,
            server_factory=lambda *_args, **_kwargs: _FakeServer(),  # type: ignore[arg-type]
        )

        self.assertTrue(graph.component_manager.is_active("core"))
        self.assertIsNotNone(graph.component_manager.command_registry.dispatch("help"))

    def test_composition_activates_tui_component_from_configuration(self) -> None:
        document = ConfigDocument(
            settings=RuntimeSettings.create(),
            components=ComponentSettings(enabled_components=("core", "tui")),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime-config.json"
            JsonConfigRepository().save(path, document)
            graph = create_runtime_object_graph(
                host="127.0.0.1",
                port=8080,
                config_path=path,
                mitm_enabled=False,
                certs_dir=None,
                edit_timeout_s=1,
                server_factory=lambda *_args, **_kwargs: _FakeServer(),  # type: ignore[arg-type]
            )

        self.assertIsNotNone(graph.tui)
        self.assertTrue(graph.component_manager.is_active("tui"))

    def test_enter_failure_releases_composed_resources(self) -> None:
        server = _FakeServer()
        application = ProxyApplication(
            ApplicationOptions(mitm_enabled=False),
            server_factory=lambda *_args, **_kwargs: server,  # type: ignore[arg-type]
        )

        with (
            patch.object(threading.Thread, "start", side_effect=RuntimeError("thread start failed")),
            self.assertRaisesRegex(RuntimeError, "thread start failed"),
        ):
            application.__enter__()

        self.assertEqual(server.tunnel_close_calls, 1)
        self.assertEqual(server.close_calls, 1)

    def test_mockserver_loads_and_persists_its_own_component_configuration(self) -> None:
        scenarios = MockScenarioStore()
        scenarios.add(
            MockScenario(
                "demo",
                "Demo",
                responses=(MockResponse("mock-rule", "GET", "http://example.com/items", body="mocked"),),
            )
        )
        document = ConfigDocument(
            settings=RuntimeSettings.create(),
            components=ComponentSettings(configurations=(("mockserver", mockserver_configuration_payload(scenarios)),)),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime-config.json"
            repository = JsonConfigRepository()
            repository.save(path, document)
            graph = create_runtime_object_graph(
                host="127.0.0.1",
                port=8080,
                config_path=path,
                mitm_enabled=False,
                certs_dir=None,
                edit_timeout_s=1,
                server_factory=lambda *_args, **_kwargs: _FakeServer(),  # type: ignore[arg-type]
            )

            self.assertEqual(graph.mockserver.store.list_scenarios(), scenarios.list_scenarios())
            result = graph.component_manager.command_registry.dispatch("mock enable demo")
            self.assertEqual(result.status_message if result else None, "Mock scenario enabled: demo")
            persisted = repository.load(path)

        payload = persisted.components.configuration_for("mockserver")
        self.assertEqual(
            payload,
            {"scenarios": [{"id": "demo", "name": "Demo", "enabled": True, "responses": [{"id": "mock-rule", "method": "GET", "url": "http://example.com/items", "status": 200, "reason": "OK", "headers": {}, "body": "mocked"}]}]},
        )

    def test_shutdown_is_idempotent_and_joins_server_thread(self) -> None:
        server = _FakeServer()
        application = ProxyApplication(
            ApplicationOptions(mitm_enabled=False),
            server_factory=lambda *_args, **_kwargs: server,  # type: ignore[arg-type]
        )

        with application:
            self.assertTrue(application.server_thread.is_alive())
            application.shutdown()
            application.shutdown()

        self.assertEqual(server.shutdown_calls, 1)
        self.assertEqual(server.tunnel_close_calls, 1)
        self.assertEqual(server.close_calls, 1)
        self.assertFalse(application.server_thread.is_alive())

    def test_headless_lifecycle_serves_request_without_importing_textual(self) -> None:
        def server_factory(host: str, port: int, **kwargs: object):
            return create_server(
                host,
                port,
                runtime_context=kwargs["runtime_context"],  # type: ignore[arg-type]
                forwarder=_StaticForwarder(),
            )

        imported_textual: list[str] = []
        real_import = __import__

        def track_import(name: str, *args: object, **kwargs: object):
            if name.startswith("textual"):
                imported_textual.append(name)
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=track_import):
            with ProxyApplication(
                ApplicationOptions(host="127.0.0.1", port=0, mitm_enabled=False),
                server_factory=server_factory,  # type: ignore[arg-type]
            ) as application:
                host, port = application.server.server_address
                connection = http.client.HTTPConnection(host, port, timeout=2)
                connection.request("GET", "/demo", headers={"Host": "example.com"})
                response = connection.getresponse()
                self.assertEqual(response.read(), b"ok")
                connection.close()

        self.assertEqual(imported_textual, [])

    def test_shutdown_cancels_pending_response_edits(self) -> None:
        server = _FakeServer()
        application = ProxyApplication(
            ApplicationOptions(edit_timeout_s=10, mitm_enabled=False),
            server_factory=lambda *_args, **_kwargs: server,  # type: ignore[arg-type]
        )
        result: list[ExchangeResponse] = []

        with application:
            original = ExchangeResponse(200, "OK", {}, b"original")
            request_thread = threading.Thread(
                target=lambda: result.append(
                    application.response_modifier.maybe_modify_response(
                        request_url="https://example.com/edit",
                        method="GET",
                        response=original,
                    )
                )
            )
            request_thread.start()
            for _ in range(100):
                if application.response_modifier.poll_pending_edit() is not None:
                    break
                time.sleep(0.001)
            application.shutdown()
            request_thread.join(timeout=1)

        self.assertFalse(request_thread.is_alive())
        self.assertEqual(result, [original])


if __name__ == "__main__":
    unittest.main()
