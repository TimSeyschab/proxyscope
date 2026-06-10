import unittest

from proxyscope.proxy.forwarding import ForwardResponse
from proxyscope.proxy.http1_response_modifier_rewriter import HTTP1ResponseModifierRewriter


class TestHTTP1ResponseModifierRewriter(unittest.TestCase):
    def test_delegates_complete_response_to_processor(self) -> None:
        seen: list[ForwardResponse] = []

        def process_response(response: ForwardResponse) -> ForwardResponse:
            seen.append(response)
            return ForwardResponse(
                status_code=response.status_code,
                reason=response.reason,
                headers={"Content-Type": "text/plain"},
                body=b"edited",
            )

        rewriter = HTTP1ResponseModifierRewriter(
            process_response=process_response,
            acquire_request_method=lambda: "GET",
        )

        raw_response = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 8\r\n\r\noriginal"
        out = rewriter.feed(raw_response)
        text = out.decode("iso-8859-1")

        self.assertEqual(seen[0].body, b"original")
        self.assertIn("Content-Length: 6", text)
        self.assertTrue(text.endswith("\r\n\r\nedited"))

    def test_preserves_original_framing_when_processor_returns_same_response(self) -> None:
        raw_response = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n4\r\ntest\r\n0\r\nX-Trailer: yes\r\n\r\n"
        rewriter = HTTP1ResponseModifierRewriter(
            process_response=lambda response: response,
            acquire_request_method=lambda: "GET",
        )

        self.assertEqual(rewriter.feed(raw_response), raw_response)

    def test_keeps_request_method_for_103_then_final_response(self) -> None:
        acquired_methods = 0

        def acquire_request_method() -> str:
            nonlocal acquired_methods
            acquired_methods += 1
            return "HEAD"

        rewriter = HTTP1ResponseModifierRewriter(
            process_response=lambda response: response,
            acquire_request_method=acquire_request_method,
        )
        early_hints = b"HTTP/1.1 103 Early Hints\r\nLink: </style.css>; rel=preload; as=style\r\n\r\n"
        final_response = b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\n"

        self.assertEqual(rewriter.feed(early_hints + final_response), early_hints + final_response)
        self.assertEqual(acquired_methods, 1)

    def test_processes_close_delimited_response_when_stream_closes(self) -> None:
        seen: list[ForwardResponse] = []
        rewriter = HTTP1ResponseModifierRewriter(
            process_response=lambda response: seen.append(response) or response,
            acquire_request_method=lambda: "GET",
        )
        raw_response = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nclose-delimited"

        self.assertEqual(rewriter.feed(raw_response), b"")
        self.assertEqual(rewriter.flush(), raw_response)
        self.assertEqual(seen[0].body, b"close-delimited")


if __name__ == "__main__":
    unittest.main()
