import pytest

from proxyscope.application.processing.headers import header_value, headers_for_body, remove_header


def test_header_lookup_is_case_insensitive_and_preserves_value():
    assert header_value({"Content-Type": "Text/Plain"}, "content-type") == "Text/Plain"
    assert header_value({}, "missing") == ""


def test_removal_deletes_all_case_variants_only():
    headers = {"Content-Length": "10", "content-length": "20", "X-Other": "kept"}
    remove_header(headers, "CONTENT-LENGTH")
    remove_header(headers, "CONTENT-LENGTH")
    assert headers == {"X-Other": "kept"}


@pytest.mark.parametrize("body", [b"", b"hello", "Gr\u00fc\u00dfe".encode("utf-8")])
def test_body_headers_replace_all_framing_variants_without_mutating_input(body):
    headers = {
        "content-length": "99",
        "Content-Length": "100",
        "transfer-encoding": "chunked",
        "TRANSFER-ENCODING": "chunked",
        "X-Other": "kept",
    }
    original = dict(headers)

    assert headers_for_body(headers, body) == {"X-Other": "kept", "Content-Length": str(len(body))}
    assert headers == original
