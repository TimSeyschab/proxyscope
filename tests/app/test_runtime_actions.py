import unittest
from unittest.mock import Mock, patch

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.runtime.actions import (
    RuntimePolicyActionService,
    RuntimeReplayActionService,
    RuntimeResponseEditActionService,
)
from proxyscope.app.runtime.journal import LoggedExchange, RequestJournal


class TestRuntimePolicyActionService(unittest.TestCase):
    def test_set_enabled_and_remove_policy(self) -> None:
        config = RuntimeConfig()
        rule_name = config.add_static_response_rule(url="https://example.com/mock", name="mock")
        actions = RuntimePolicyActionService(config)

        self.assertEqual(actions.set_enabled(rule_name, enabled=False), "Policy disabled: mock")
        rule = config.get_policy_rule(rule_name)
        self.assertIsNotNone(rule)
        assert rule is not None
        self.assertFalse(rule.enabled)

        self.assertEqual(actions.remove(rule_name), "Policy removed: mock")
        self.assertIsNone(config.get_policy_rule(rule_name))

    def test_pending_edit_is_consumed(self) -> None:
        config = RuntimeConfig()
        rule_name = config.add_static_response_rule(url="https://example.com/mock", name="mock")
        actions = RuntimePolicyActionService(config)
        actions.schedule_edit(rule_name)

        with patch(
            "proxyscope.app.runtime.actions.edit_policy_rule_with_external_editor",
            return_value=(False, None, "cancelled"),
        ):
            message = actions.process_pending_edit()

        self.assertEqual(message, "cancelled")
        self.assertIsNone(actions.pending_edit_name)


class TestRuntimeReplayActionService(unittest.TestCase):
    def test_replay_builds_request_url_and_returns_message(self) -> None:
        entry = _request_entry(path="/api", target_host="example.com", target_port=443, protocol="https-mitm")
        actions = RuntimeReplayActionService(proxy_base_url="http://127.0.0.1:8080")

        with patch(
            "proxyscope.app.runtime.actions.edit_and_resend_logged_request",
            return_value=(True, "replayed"),
        ) as replay:
            message = actions.replay(entry)

        self.assertEqual(message, "replayed")
        replay.assert_called_once_with(
            entry,
            request_url="https://example.com/api",
            proxy_base_url="http://127.0.0.1:8080",
        )


class TestRuntimeResponseEditActionService(unittest.TestCase):
    def test_failed_pending_edit_keeps_original_response(self) -> None:
        pending = Mock()
        modifier = Mock()
        modifier.poll_pending_edit.return_value = pending
        actions = RuntimeResponseEditActionService(modifier)

        with patch(
            "proxyscope.app.runtime.actions.edit_pending_response_with_external_editor",
            return_value=(False, "cancelled"),
        ):
            message = actions.process_pending_edit()

        self.assertEqual(message, "cancelled")
        pending.keep_original.assert_called_once_with()


def _request_entry(
    *,
    path: str,
    target_host: str | None,
    target_port: int | None,
    protocol: str,
) -> LoggedExchange:
    journal = RequestJournal()
    request_id = journal.start_request(
        method="GET",
        path=path,
        start_line=f"GET {path} HTTP/1.1",
        headers={},
        body=b"",
        client_ip="127.0.0.1",
        target_host=target_host,
        target_port=target_port,
        protocol=protocol,
    )
    entry = journal.get_entry(request_id)
    assert entry is not None
    return entry


if __name__ == "__main__":
    unittest.main()
