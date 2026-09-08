import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from proxyscope.adapters.replay import requests_adapter as replay
from tests.support.exchanges import recorded_exchange


@pytest.mark.parametrize("proxy", [None, "http://127.0.0.1:8080"])
@pytest.mark.parametrize("body", [None, b"", b"text", b"\xff\x00"])
def test_replay_edits_payload_sanitizes_headers_and_routes_request(monkeypatch, proxy, body):
    entry = recorded_exchange()
    entry = replace(entry, request=replace(entry.request, body=body))
    monkeypatch.setattr(replay, "_resolve_editor_command", lambda: "editor")

    def edit(_editor, path):
        payload = json.loads(path.read_text())
        payload["headers"] = {"host": "old.test", "CONTENT-LENGTH": "999", "connection": "close", "X-Keep": "yes"}
        path.write_text(json.dumps(payload))

    monkeypatch.setattr(replay, "_run_editor", edit)
    request = Mock(return_value=Mock(status_code=202, reason="Accepted"))
    monkeypatch.setattr(replay.requests, "request", request)
    success, message = replay.edit_and_resend_logged_request(
        entry, request_url="https://api.test/items", proxy_base_url=proxy
    )
    assert success
    assert message == "Replayed GET https://api.test/items -> 202 Accepted"
    request.assert_called_once_with(
        "GET",
        "https://api.test/items",
        headers={"X-Keep": "yes"},
        data=body or b"",
        timeout=60,
        allow_redirects=False,
        proxies=None if proxy is None else {"http": proxy, "https": proxy},
        verify=proxy is None,
    )


def test_missing_editor_does_not_send_request(monkeypatch):
    monkeypatch.setattr(replay, "_resolve_editor_command", lambda: None)
    request = Mock()
    monkeypatch.setattr(replay.requests, "request", request)
    success, message = replay.edit_and_resend_logged_request(
        recorded_exchange(), request_url="http://api.test/", proxy_base_url=None
    )
    assert not success
    assert message.startswith("No editor found")
    request.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"method": " ", "url": "http://api.test"},
        {},
        {"url": "file:///etc/hosts"},
        {"url": "http://api.test", "body_base64": "%%%"},
    ],
)
def test_invalid_edited_payload_never_reaches_network(monkeypatch, payload):
    monkeypatch.setattr(replay, "_resolve_editor_command", lambda: "editor")
    monkeypatch.setattr(replay, "_run_editor", lambda editor, path: path.write_text(json.dumps(payload)))
    request = Mock()
    monkeypatch.setattr(replay.requests, "request", request)
    success, message = replay.edit_and_resend_logged_request(
        recorded_exchange(), request_url="http://api.test/", proxy_base_url=None
    )
    assert not success
    assert message.startswith("Replay failed")
    request.assert_not_called()
