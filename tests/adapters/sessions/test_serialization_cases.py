import json
from dataclasses import replace

import pytest

from proxyscope.adapters.sessions.json_export import export_entries, load_entries_from_json
from tests.support.exchanges import recorded_exchange


@pytest.mark.parametrize("body", [None, b"", b"text", b"\xff\x00"])
@pytest.mark.parametrize("completed", [False, True])
def test_json_roundtrip_preserves_missing_empty_text_and_binary_bodies(tmp_path, body, completed):
    entry = recorded_exchange(status=200 if completed else None)
    entry = replace(entry, request=replace(entry.request, body=body))
    if entry.response is not None:
        entry = replace(
            entry, response=replace(entry.response, body=body, body_size=None if body is None else len(body))
        )
    path = export_entries([entry], format_name="JSON", destination=tmp_path / "nested" / "session.json")
    (restored,) = load_entries_from_json(path)
    assert restored.request == entry.request
    assert restored.target_host == entry.target_host
    assert restored.duration_ms == entry.duration_ms
    if completed:
        assert restored.response.body == body
        assert restored.response.body_size == entry.response.body_size
    else:
        assert restored.response is None
        assert restored.finished_at is None


@pytest.mark.parametrize(
    "protocol,port,path,expected",
    [
        ("http", None, "items", "http://api.test/items"),
        ("http", 80, "/items", "http://api.test/items"),
        ("https-mitm", 443, "/items", "https://api.test/items"),
        ("https", 8443, "/items", "https://api.test:8443/items"),
        ("http", 80, "https://other.test/path", "https://other.test/path"),
    ],
)
def test_har_urls_preserve_scheme_ports_and_absolute_targets(tmp_path, protocol, port, path, expected):
    entry = recorded_exchange(protocol=protocol, port=port, path=path, status=None)
    destination = export_entries([entry], format_name="har", destination=tmp_path / "session.har")
    exported = json.loads(destination.read_text())["log"]["entries"][0]
    assert exported["request"]["url"] == expected
    assert exported["response"]["status"] == 0


@pytest.mark.parametrize("body", [None, b"", b"text", b"\xff"])
@pytest.mark.parametrize("start_line", ["", "unknown", "HTTP/1.0 response", "GET / HTTP/2"])
def test_har_body_encoding_and_http_version(tmp_path, body, start_line):
    entry = recorded_exchange()
    entry = replace(
        entry,
        request=replace(entry.request, body=body, start_line=start_line, headers=(("content-type", "text/plain"),)),
    )
    destination = export_entries([entry], format_name="har", destination=tmp_path / "session.har")
    request = json.loads(destination.read_text())["log"]["entries"][0]["request"]
    expected_version = (
        "HTTP/1.0" if start_line.startswith("HTTP/1.0") else "HTTP/2" if start_line.endswith("HTTP/2") else "HTTP/1.1"
    )
    assert request["httpVersion"] == expected_version
    if body is None:
        assert "postData" not in request
    else:
        assert request["postData"]["mimeType"] == "text/plain"
        assert request["postData"]["text"] == ("/w==" if body == b"\xff" else body.decode())
        assert request["postData"].get("encoding") == ("base64" if body == b"\xff" else None)


@pytest.mark.parametrize("payload", [{}, {"entries": {}}, {"entries": [None]}, {"entries": [{}]}])
def test_malformed_session_structure_is_rejected(tmp_path, payload):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_entries_from_json(path)


@pytest.mark.parametrize("field", ["target_port", "duration_ms"])
def test_invalid_numeric_metadata_is_rejected(tmp_path, field):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"entries": [{"request": {}, field: []}]}))
    with pytest.raises(ValueError):
        load_entries_from_json(path)


def test_minimal_session_uses_optional_metadata_defaults(tmp_path):
    path = tmp_path / "minimal.json"
    path.write_text(json.dumps({"entries": [{"request": {}}]}))
    (entry,) = load_entries_from_json(path)
    assert entry.started_at == 0
    assert entry.target_host is entry.target_port is entry.duration_ms is None
    assert entry.request.headers == ()
    assert entry.request.body is None


def test_unknown_export_format_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unsupported export format"):
        export_entries([], format_name="xml", destination=tmp_path / "file.xml")
