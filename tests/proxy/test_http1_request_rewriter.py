import unittest

from proxyscope.proxy.http1_request_rewriter import HTTP1RequestHeaderRewriter, rewrite_cache_invalidation_headers


class TestHTTP1RequestHeaderRewriter(unittest.TestCase):
    def test_rewrite_cache_invalidation_headers(self) -> None:
        headers = rewrite_cache_invalidation_headers(
            {
                "Host": "example.com",
                "If-None-Match": '"etag-1"',
                "If-Modified-Since": "Mon, 01 Jan 2024 00:00:00 GMT",
            }
        )
        lowered = {key.lower(): value for key, value in headers.items()}
        self.assertNotIn("if-none-match", lowered)
        self.assertNotIn("if-modified-since", lowered)
        self.assertEqual(lowered["cache-control"], "no-cache, no-store, max-age=0, must-revalidate")
        self.assertEqual(lowered["pragma"], "no-cache")
        self.assertEqual(lowered["expires"], "0")
        self.assertEqual(lowered["accept-encoding"], "identity")

    def test_rewriter_removes_conditional_headers(self) -> None:
        rewriter = HTTP1RequestHeaderRewriter()
        raw = (
            b"GET /x HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"If-None-Match: \"abc\"\r\n"
            b"If-Modified-Since: Mon, 01 Jan 2024 00:00:00 GMT\r\n"
            b"\r\n"
        )
        rewritten = rewriter.feed(raw)
        text = rewritten.decode("iso-8859-1")
        self.assertIn("GET /x HTTP/1.1", text)
        self.assertNotIn("If-None-Match:", text)
        self.assertNotIn("If-Modified-Since:", text)
        self.assertIn("Cache-Control: no-cache, no-store, max-age=0, must-revalidate", text)
        self.assertIn("Pragma: no-cache", text)
        self.assertIn("Expires: 0", text)
        self.assertIn("Accept-Encoding: identity", text)

    def test_rewriter_handles_split_header_chunks(self) -> None:
        rewriter = HTTP1RequestHeaderRewriter()
        part1 = b"GET /x HTTP/1.1\r\nHost: example.com\r\nIf-None-Match: \"abc\""
        part2 = b"\r\n\r\n"
        out1 = rewriter.feed(part1)
        out2 = rewriter.feed(part2)
        self.assertEqual(out1, b"")
        text = out2.decode("iso-8859-1")
        self.assertNotIn("If-None-Match:", text)
        self.assertIn("GET /x HTTP/1.1", text)
        self.assertIn("Cache-Control:", text)
