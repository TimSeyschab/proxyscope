import pytest

from proxyscope.adapters.proxy.http1.request_rewriter import HTTP1RequestHeaderRewriter


@pytest.mark.parametrize("fragment_size", [1, 2, 7, 4096])
@pytest.mark.parametrize(
    ("framing", "body"),
    [
        (b"Content-Length: 7\r\n", b"a\r\n\r\nbc"),
        (b"Transfer-Encoding: chunked\r\n", b"3;ext=yes\r\nabc\r\n0\r\n\r\n"),
        (b"Transfer-Encoding: chunked\r\n", b"3\r\nabc\r\n0\r\nX-Trailer: yes\r\n\r\n"),
        (b"Content-Length: 0\r\n", b""),
    ],
)
def test_fragmented_bodies_preserve_bytes_and_allow_next_request(fragment_size, framing, body):
    rewriter = HTTP1RequestHeaderRewriter(lambda headers: {**headers, "X-Rewritten": "yes"})
    first = b"POST /first HTTP/1.1\r\n" + framing + b"\r\n"
    second = b"GET /second HTTP/1.1\r\nHost: api.test\r\n\r\n"
    wire = first + body + second
    output = b"".join(
        rewriter.feed(wire[start : start + fragment_size]) for start in range(0, len(wire), fragment_size)
    )
    expected = first[:-2] + b"X-Rewritten: yes\r\n\r\n" + body + second[:-2] + b"X-Rewritten: yes\r\n\r\n"
    assert output == expected
    assert rewriter.flush() == b""


@pytest.mark.parametrize("length", [b"invalid", b"-1"])
def test_invalid_content_length_does_not_stall_next_request(length):
    rewriter = HTTP1RequestHeaderRewriter(lambda headers: headers)
    wire = b"GET / HTTP/1.1\r\nContent-Length: " + length + b"\r\n\r\nGET /next HTTP/1.1\r\n\r\n"
    assert rewriter.feed(wire) == wire


def test_malformed_chunk_passes_buffer_through_and_recovers():
    rewriter = HTTP1RequestHeaderRewriter(lambda headers: headers)
    wire = b"POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\ninvalid\r\nbody"
    assert rewriter.feed(wire) == wire
    assert rewriter.feed(b"GET /next HTTP/1.1\r\n\r\n") == b"GET /next HTTP/1.1\r\n\r\n"


def test_flush_returns_partial_header_only_once():
    rewriter = HTTP1RequestHeaderRewriter()
    assert rewriter.feed(b"GET / HTTP/1.1\r\nHost:") == b""
    assert rewriter.flush() == b"GET / HTTP/1.1\r\nHost:"
    assert rewriter.flush() == b""


def test_malformed_header_lines_are_ignored():
    rewriter = HTTP1RequestHeaderRewriter(lambda headers: headers)
    assert (
        rewriter.feed(b"GET / HTTP/1.1\r\nbroken\r\n Host : api.test \r\n\r\n")
        == b"GET / HTTP/1.1\r\nHost: api.test\r\n\r\n"
    )
