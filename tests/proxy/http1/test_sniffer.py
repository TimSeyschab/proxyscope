import unittest

from proxyscope.proxy.http1.sniffer import HTTP1MessageSniffer


class TestHTTP1MessageSniffer(unittest.TestCase):
    def test_parses_request_with_content_length_body(self) -> None:
        seen: list[tuple[str, dict[str, str], bytes]] = []
        sniffer = HTTP1MessageSniffer(lambda start_line, headers, body: seen.append((start_line, headers, body)))

        sniffer.feed((b"POST /submit HTTP/1.1\r\nHost: example.com\r\nContent-Length: 5\r\n\r\nhello"))

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "POST /submit HTTP/1.1")
        self.assertEqual(seen[0][1]["Host"], "example.com")
        self.assertEqual(seen[0][2], b"hello")

    def test_parses_chunked_response(self) -> None:
        seen: list[tuple[str, dict[str, str], bytes]] = []
        sniffer = HTTP1MessageSniffer(lambda start_line, headers, body: seen.append((start_line, headers, body)))

        sniffer.feed((b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n4\r\nWiki\r\n5\r\npedia\r\n0\r\n\r\n\r\n"))

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "HTTP/1.1 200 OK")
        self.assertEqual(seen[0][1]["Transfer-Encoding"], "chunked")
        self.assertEqual(seen[0][2], b"Wikipedia")

    def test_parses_multiple_messages_in_sequence(self) -> None:
        seen: list[str] = []
        sniffer = HTTP1MessageSniffer(lambda start_line, _headers, _body: seen.append(start_line))

        sniffer.feed((b"GET /a HTTP/1.1\r\nHost: example.com\r\n\r\nGET /b HTTP/1.1\r\nHost: example.com\r\n\r\n"))

        self.assertEqual(seen, ["GET /a HTTP/1.1", "GET /b HTTP/1.1"])
