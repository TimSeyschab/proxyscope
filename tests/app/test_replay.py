import unittest

from proxyscope.adapters.replay.requests_adapter import _build_edit_payload, _parse_replay_payload
from proxyscope.application.journal import LoggedExchange, LoggedRequestMessage


class TestReplayPayloads(unittest.TestCase):
    def test_build_payload_uses_full_body_not_preview(self) -> None:
        entry = LoggedExchange(
            request_id=1,
            started_at=0.0,
            finished_at=None,
            duration_ms=None,
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
            request=LoggedRequestMessage(
                method="POST",
                path="/submit",
                start_line="POST /submit HTTP/1.1",
                headers=(("Content-Type", "application/json"),),
                body_preview='{"truncated":true}',
                body=b'{"full":true}',
            ),
            response=None,
        )

        payload = _build_edit_payload(entry, request_url="http://example.com/submit")

        self.assertEqual(payload["body_text"], '{"full":true}')

    def test_build_payload_uses_base64_for_binary_body(self) -> None:
        entry = LoggedExchange(
            request_id=1,
            started_at=0.0,
            finished_at=None,
            duration_ms=None,
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
            request=LoggedRequestMessage(
                method="POST",
                path="/bin",
                start_line="POST /bin HTTP/1.1",
                headers=(),
                body_preview="abc\\x00def",
                body=b"\xff\x00\x01",
            ),
            response=None,
        )

        payload = _build_edit_payload(entry, request_url="http://example.com/bin")

        self.assertNotIn("body_text", payload)
        self.assertEqual(payload["body_encoding"], "base64")
        self.assertEqual(payload["body_base64"], "/wAB")

    def test_parse_payload_prefers_base64_body(self) -> None:
        replay = _parse_replay_payload(
            {
                "method": "POST",
                "url": "https://example.com/upload",
                "headers": {"Content-Type": "application/octet-stream"},
                "body_base64": "/wAB",
            }
        )

        self.assertEqual(replay["body"], b"\xff\x00\x01")

    def test_parse_payload_rejects_invalid_base64(self) -> None:
        with self.assertRaisesRegex(ValueError, "body_base64 must be valid base64"):
            _parse_replay_payload(
                {
                    "method": "POST",
                    "url": "https://example.com/upload",
                    "body_base64": "not-base64",
                }
            )


if __name__ == "__main__":
    unittest.main()
