import unittest

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.policies.engine import PolicyEngine
from proxyscope.proxy.forwarding import ForwardResponse
from proxyscope.proxy.http1_response_modifier_rewriter import HTTP1ResponseModifierRewriter


class _FakeModifier:
    def __init__(self) -> None:
        self.seen_urls: list[str] = []

    def maybe_modify_response(self, *, request_url: str, method: str, response: ForwardResponse) -> ForwardResponse:
        self.seen_urls.append(request_url)
        if request_url == "https://example.com/edit":
            return ForwardResponse(
                status_code=response.status_code,
                reason=response.reason,
                headers={"Content-Type": "text/plain"},
                body=b"edited",
            )
        return response


class TestHTTP1ResponseModifierRewriter(unittest.TestCase):
    def test_rewrites_matching_response(self) -> None:
        modifier = _FakeModifier()
        requests = [("GET", "https://example.com/edit")]

        def acquire_request_meta() -> tuple[str, str] | None:
            if not requests:
                return None
            return requests.pop(0)

        rewriter = HTTP1ResponseModifierRewriter(
            policy_evaluator=PolicyEngine(RuntimeConfig().policy_repository),
            response_modifier=modifier,  # type: ignore[arg-type]
            acquire_request_meta=acquire_request_meta,
        )

        raw_response = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 8\r\n\r\noriginal"
        out = rewriter.feed(raw_response)
        text = out.decode("iso-8859-1")
        self.assertIn("HTTP/1.1 200 OK", text)
        self.assertIn("Content-Length: 6", text)
        self.assertTrue(text.endswith("\r\n\r\nedited"))
        self.assertEqual(modifier.seen_urls, ["https://example.com/edit"])

    def test_can_replace_response_with_static_policy_template(self) -> None:
        config = RuntimeConfig()
        config.add_static_response_rule(
            url="https://example.com/mock",
            status_code=202,
            reason="Accepted",
            headers={"Content-Type": "text/plain"},
            body=b"from-policy",
            method="GET",
        )
        modifier = _FakeModifier()
        requests = [("GET", "https://example.com/mock")]

        def acquire_request_meta() -> tuple[str, str] | None:
            if not requests:
                return None
            return requests.pop(0)

        rewriter = HTTP1ResponseModifierRewriter(
            policy_evaluator=PolicyEngine(config.policy_repository),
            response_modifier=modifier,  # type: ignore[arg-type]
            acquire_request_meta=acquire_request_meta,
        )

        raw_response = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 8\r\n\r\noriginal"
        out = rewriter.feed(raw_response)
        text = out.decode("iso-8859-1")
        self.assertIn("HTTP/1.1 202 Accepted", text)
        self.assertIn("Content-Length: 11", text)
        self.assertTrue(text.endswith("\r\n\r\nfrom-policy"))
        self.assertEqual(modifier.seen_urls, [])

    def test_static_policy_takes_precedence_over_editor_modifier(self) -> None:
        config = RuntimeConfig()
        config.add_modification_whitelist_entry("https://example.com/edit")
        config.add_static_response_rule(
            url="https://example.com/edit",
            status_code=203,
            reason="Non-Authoritative Information",
            headers={"Content-Type": "text/plain"},
            body=b"from-static-policy",
            method="GET",
        )
        modifier = _FakeModifier()
        requests = [("GET", "https://example.com/edit")]

        def acquire_request_meta() -> tuple[str, str] | None:
            if not requests:
                return None
            return requests.pop(0)

        rewriter = HTTP1ResponseModifierRewriter(
            policy_evaluator=PolicyEngine(config.policy_repository),
            response_modifier=modifier,  # type: ignore[arg-type]
            acquire_request_meta=acquire_request_meta,
        )

        raw_response = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 8\r\n\r\noriginal"
        out = rewriter.feed(raw_response)
        text = out.decode("iso-8859-1")
        self.assertIn("HTTP/1.1 203 Non-Authoritative Information", text)
        self.assertTrue(text.endswith("\r\n\r\nfrom-static-policy"))
        self.assertEqual(modifier.seen_urls, [])

    def test_keeps_request_meta_for_103_then_final_response(self) -> None:
        modifier = _FakeModifier()
        requests = [("GET", "https://example.com/edit")]

        def acquire_request_meta() -> tuple[str, str] | None:
            if not requests:
                return None
            return requests.pop(0)

        rewriter = HTTP1ResponseModifierRewriter(
            policy_evaluator=PolicyEngine(RuntimeConfig().policy_repository),
            response_modifier=modifier,  # type: ignore[arg-type]
            acquire_request_meta=acquire_request_meta,
        )

        early_hints = b"HTTP/1.1 103 Early Hints\r\nLink: </style.css>; rel=preload; as=style\r\n\r\n"
        final_response = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 8\r\n\r\noriginal"

        out = rewriter.feed(early_hints + final_response)
        text = out.decode("iso-8859-1")
        self.assertIn("HTTP/1.1 103 Early Hints", text)
        self.assertIn("HTTP/1.1 200 OK", text)
        self.assertTrue(text.endswith("\r\n\r\nedited"))
        self.assertEqual(modifier.seen_urls, ["https://example.com/edit"])
