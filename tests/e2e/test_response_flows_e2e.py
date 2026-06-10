import http.client
import queue
import socketserver
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from proxyscope.app.config.runtime import RuntimeConfig, set_runtime_config
from proxyscope.app.editing.modifier import ResponseModifierService, set_response_modifier
from proxyscope.app.runtime.journal import RequestJournal, get_request_journal, set_request_journal
from proxyscope.proxy.server import create_server


class _UpstreamHandler(socketserver.BaseRequestHandler):
    response_status = b"200 OK"
    response_body = b"upstream-body"
    call_count = 0

    def handle(self) -> None:
        type(self).call_count += 1
        request_data = b""
        while b"\r\n\r\n" not in request_data:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            request_data += chunk
        response = (
            b"HTTP/1.1 "
            + self.response_status
            + b"\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: "
            + str(len(self.response_body)).encode("ascii")
            + b"\r\n\r\n"
            + self.response_body
        )
        self.request.sendall(response)


class TestResponseFlowsE2E(unittest.TestCase):
    def setUp(self) -> None:
        set_runtime_config(RuntimeConfig())
        set_request_journal(RequestJournal())
        set_response_modifier(ResponseModifierService(interactive_enabled=False))

    def tearDown(self) -> None:
        set_runtime_config(RuntimeConfig())
        set_request_journal(RequestJournal())
        set_response_modifier(ResponseModifierService(interactive_enabled=False))

    def _proxy_request(
        self,
        *,
        host: str,
        port: int,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection(host, port, timeout=3)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        status = response.status
        body_bytes = response.read()
        headers_map = {key.lower(): value for key, value in response.getheaders()}
        conn.close()
        return status, headers_map, body_bytes

    def test_e2e_manual_response_edit_updates_client_and_journal(self) -> None:
        upstream = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _UpstreamHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()

        proxy = create_server("127.0.0.1", 0, auto_enable_mitm=False)
        proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        proxy_thread.start()
        proxy_host, proxy_port = proxy.server_address

        try:
            upstream_host, upstream_port = upstream.server_address
            target_url = f"http://{upstream_host}:{upstream_port}/manual-edit"

            config = RuntimeConfig()
            config.add_open_editor_policy(target_url, method="GET")
            set_runtime_config(config)

            response_modifier = ResponseModifierService(interactive_enabled=True)
            set_response_modifier(response_modifier)

            result_queue: queue.Queue[tuple[int, dict[str, str], bytes] | Exception] = queue.Queue()

            def perform_request() -> None:
                try:
                    result_queue.put(
                        self._proxy_request(
                            host=proxy_host,
                            port=proxy_port,
                            method="GET",
                            path=target_url,
                            headers={"Host": f"{upstream_host}:{upstream_port}"},
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    result_queue.put(exc)

            request_thread = threading.Thread(target=perform_request, daemon=True)
            request_thread.start()

            pending = None
            for _ in range(100):
                pending = response_modifier.poll_pending_edit()
                if pending is not None:
                    break
                time.sleep(0.01)
            self.assertIsNotNone(pending)
            assert pending is not None
            pending.apply(
                headers={"Content-Type": "text/plain; charset=utf-8", "X-Edited": "yes"},
                body=b"edited-body",
            )

            request_thread.join(timeout=2)
            self.assertFalse(request_thread.is_alive())
            result = result_queue.get(timeout=1)
            if isinstance(result, Exception):
                raise result
            status, headers_map, body = result

            self.assertEqual(status, 200)
            self.assertEqual(body, b"edited-body")
            self.assertEqual(headers_map.get("x-edited"), "yes")
            self.assertEqual(headers_map.get("content-length"), str(len(b"edited-body")))

            entry = get_request_journal().list_entries()[-1]
            self.assertIsNotNone(entry.response)
            assert entry.response is not None
            self.assertEqual(entry.response.status_code, 200)
            self.assertIn("edited-body", entry.response.body_preview)
        finally:
            proxy.shutdown()
            proxy.server_close()
            proxy_thread.join(timeout=2)
            upstream.shutdown()
            upstream.server_close()
            upstream_thread.join(timeout=2)

    def test_e2e_config_static_response_is_displayed_and_bypasses_upstream(self) -> None:
        _UpstreamHandler.call_count = 0
        upstream = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _UpstreamHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()

        proxy = create_server("127.0.0.1", 0, auto_enable_mitm=False)
        proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        proxy_thread.start()
        proxy_host, proxy_port = proxy.server_address

        try:
            upstream_host, upstream_port = upstream.server_address
            target_url = f"http://{upstream_host}:{upstream_port}/cfg-edit"

            with TemporaryDirectory() as tmp_dir:
                config_path = Path(tmp_dir) / "runtime.json"
                config = RuntimeConfig()
                config.add_static_response_rule(
                    url=target_url,
                    status_code=299,
                    reason="Config Override",
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                    body=b"config-edited-response",
                    method="GET",
                )
                config.save_to_path(config_path)

                loaded = RuntimeConfig.load_from_file(config_path)
                set_runtime_config(loaded)

            status, _headers, body = self._proxy_request(
                host=proxy_host,
                port=proxy_port,
                method="GET",
                path=target_url,
                headers={"Host": f"{upstream_host}:{upstream_port}"},
            )

            self.assertEqual(status, 299)
            self.assertEqual(body, b"config-edited-response")
            self.assertEqual(_UpstreamHandler.call_count, 0)

            entry = get_request_journal().list_entries()[-1]
            self.assertIsNotNone(entry.response)
            assert entry.response is not None
            self.assertEqual(entry.response.status_code, 299)
            self.assertIn("config-edited-response", entry.response.body_preview)
        finally:
            proxy.shutdown()
            proxy.server_close()
            proxy_thread.join(timeout=2)
            upstream.shutdown()
            upstream.server_close()
            upstream_thread.join(timeout=2)
