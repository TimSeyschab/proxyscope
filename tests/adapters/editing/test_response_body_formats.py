import gzip
import sys
import zlib
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from proxyscope.adapters.editing import response_editor as editor
from proxyscope.application.processing.models import ExchangeResponse
from proxyscope.application.response_edits import PendingResponseEdit


def pending_response(headers, body):
    return PendingResponseEdit("http://api.test/items", "GET", ExchangeResponse(200, "OK", headers, body), Event())


@pytest.mark.parametrize("encoding,compress", [("gzip", gzip.compress), ("deflate", zlib.compress)])
def test_compressed_text_is_decoded_for_editing_and_sent_uncompressed(monkeypatch, encoding, compress):
    pending = pending_response({"Content-Type": "text/plain", "content-encoding": encoding}, compress(b"original"))
    monkeypatch.setattr(editor, "_resolve_editor_command", lambda: "editor")

    def edit(_command, path):
        if path.name == "body.txt":
            assert path.read_text() == "original"
            path.write_text("edited")

    monkeypatch.setattr(editor, "_run_editor", edit)
    result = editor.edit_pending_response_with_external_editor(pending)
    assert result.success
    assert result.body == b"edited"
    assert "content-encoding" not in result.headers
    assert pending.wait(timeout_s=0).headers == {"Content-Type": "text/plain", "Content-Length": "6"}


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "unknown"])
def test_undecodable_compressed_body_is_preserved_as_binary(monkeypatch, encoding):
    pending = pending_response({"Content-Type": "text/plain", "Content-Encoding": encoding}, b"not compressed")
    monkeypatch.setattr(editor, "_resolve_editor_command", lambda: "editor")
    monkeypatch.setattr(editor, "_run_editor", lambda *_: None)
    result = editor.edit_pending_response_with_external_editor(pending)
    assert result.success
    assert result.body == b"not compressed"
    assert result.headers["Content-Encoding"] == encoding


@pytest.mark.parametrize(
    "content_type,body",
    [
        ("application/octet-stream", b"\x00\xff"),
        ("application/octet-stream", b"\xff"),
        ("application/octet-stream", b"plain text"),
        ("text/plain", b""),
        ('text/plain; extra=1; charset="iso-8859-1"', b"caf\xe9"),
        ("text/plain; charset=", b"text"),
    ],
)
def test_text_binary_and_charset_roundtrips(monkeypatch, content_type, body):
    pending = pending_response({"Content-Type": content_type, "Content-Encoding": "identity"}, body)
    monkeypatch.setattr(editor, "_resolve_editor_command", lambda: "editor")
    monkeypatch.setattr(editor, "_run_editor", lambda *_: None)
    result = editor.edit_pending_response_with_external_editor(pending)
    assert result.success
    assert result.body == body


def test_header_editor_ignores_comments_blank_and_malformed_lines(monkeypatch):
    pending = pending_response({}, b"body")
    monkeypatch.setattr(editor, "_resolve_editor_command", lambda: "editor")

    def edit(_command, path):
        if path.name == "headers.txt":
            path.write_text("\n# comment\nmalformed\n X-Test : value:with:colon \n")

    monkeypatch.setattr(editor, "_run_editor", edit)
    result = editor.edit_pending_response_with_external_editor(pending)
    assert result.success
    assert result.headers == {"X-Test": "value:with:colon"}


def test_no_editor_completes_pending_task_with_original(monkeypatch):
    pending = pending_response({}, b"original")
    monkeypatch.setattr(editor, "_resolve_editor_command", lambda: None)
    result = editor.edit_pending_response_with_external_editor(pending)
    assert not result.success
    assert pending.is_done
    assert pending.wait(timeout_s=0) is pending.response


@pytest.mark.parametrize("available,decode_fails", [(False, False), (True, False), (True, True)])
def test_optional_brotli_support_and_decoder_failure(monkeypatch, available, decode_fails):
    decoder = Mock(return_value=b"decoded", side_effect=ValueError("bad stream") if decode_fails else None)
    monkeypatch.setitem(sys.modules, "brotli", SimpleNamespace(decompress=decoder) if available else None)
    pending = pending_response({"Content-Type": "text/plain", "Content-Encoding": "br"}, b"encoded")
    monkeypatch.setattr(editor, "_resolve_editor_command", lambda: "editor")
    monkeypatch.setattr(editor, "_run_editor", lambda *_: None)
    result = editor.edit_pending_response_with_external_editor(pending)
    assert result.success
    assert result.body == (b"decoded" if available and not decode_fails else b"encoded")
    assert ("Content-Encoding" in result.headers) is (not available or decode_fails)
