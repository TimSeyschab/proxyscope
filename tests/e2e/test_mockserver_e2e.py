import http.client
import json
import tempfile
import threading
from pathlib import Path

from proxyscope.application.events import MockResponseServed
from proxyscope.bootstrap.composition import create_runtime_object_graph


def test_mockserver_configuration_serves_response_through_proxy() -> None:
    payload = {
        "schema_version": 1,
        "settings": {"mitm_enabled": False},
        "components": {
            "enabled": ["core", "mockserver"],
            "configurations": {
                "mockserver": {
                    "scenarios": [
                        {
                            "id": "offline",
                            "enabled": True,
                            "responses": [
                                {
                                    "id": "catalog",
                                    "method": "GET",
                                    "url": "http://api.example.test/catalog",
                                    "status": 503,
                                    "reason": "Service Unavailable",
                                    "headers": {"Content-Type": "application/json"},
                                    "body": '{"error": "offline"}',
                                }
                            ],
                        }
                    ]
                }
            },
        },
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "runtime-config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        graph = create_runtime_object_graph(
            host="127.0.0.1",
            port=0,
            config_path=path,
            mitm_enabled=False,
            certs_dir=None,
            edit_timeout_s=1,
        )
        events: list[MockResponseServed] = []
        graph.event_bus.subscribe(lambda event: events.append(event) if isinstance(event, MockResponseServed) else None)
        thread = threading.Thread(target=graph.server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = graph.server.server_address
            connection = http.client.HTTPConnection(host, port, timeout=3)
            connection.request(
                "GET",
                "http://api.example.test/catalog",
                headers={"Host": "api.example.test"},
            )
            response = connection.getresponse()

            assert response.status == 503
            assert response.reason == "Service Unavailable"
            assert response.read() == b'{"error": "offline"}'
            assert response.getheader("Content-Type") == "application/json"
            assert [(event.rule_id, event.scenario_id, event.status_code) for event in events] == [
                ("mockserver:offline:catalog", "offline", 503)
            ]
        finally:
            connection.close()
            graph.server.shutdown()
            graph.server.server_close()
            thread.join(timeout=2)
            graph.event_bus.shutdown()
            graph.event_store.close()
