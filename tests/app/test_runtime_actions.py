import unittest
from unittest.mock import Mock

from proxyscope.application.actions import (
    RuntimePolicyActionService,
    RuntimeReplayActionService,
    RuntimeResponseEditActionService,
)
from proxyscope.application.journal import LoggedExchange, RequestJournal
from tests.support.runtime_context import RuntimeTestContext


class TestRuntimePolicyActionService(unittest.TestCase):
    def test_successful_policy_mutation_is_persisted_explicitly(self) -> None:
        config = RuntimeTestContext()
        rule_name = config.add_static_response_rule(url="https://example.com/mock", name="mock")
        configuration = Mock()
        actions = RuntimePolicyActionService(
            config.policy_administration,
            configuration,
            policy_editor=Mock(),
        )

        actions.set_enabled(rule_name, enabled=False)

        configuration.save.assert_called_once_with()

    def test_set_enabled_and_remove_policy(self) -> None:
        config = RuntimeTestContext()
        rule_name = config.add_static_response_rule(url="https://example.com/mock", name="mock")
        actions = RuntimePolicyActionService(
            config.policy_administration,
            config.configuration,
            policy_editor=Mock(),
        )

        self.assertEqual(actions.set_enabled(rule_name, enabled=False), "Policy disabled: mock")
        rule = config.get_policy_rule(rule_name)
        self.assertIsNotNone(rule)
        assert rule is not None
        self.assertFalse(rule.enabled)

        self.assertEqual(actions.remove(rule_name), "Policy removed: mock")
        self.assertIsNone(config.get_policy_rule(rule_name))

    def test_pending_edit_is_consumed(self) -> None:
        config = RuntimeTestContext()
        rule_name = config.add_static_response_rule(url="https://example.com/mock", name="mock")
        policy_editor = Mock(return_value=(False, None, "cancelled"))
        actions = RuntimePolicyActionService(
            config.policy_administration,
            config.configuration,
            policy_editor=policy_editor,
        )
        actions.schedule_edit(rule_name)

        message = actions.process_pending_edit()

        self.assertEqual(message, "cancelled")
        self.assertIsNone(actions.pending_edit_name)


class TestRuntimeReplayActionService(unittest.TestCase):
    def test_replay_builds_request_url_and_returns_message(self) -> None:
        entry = _request_entry(path="/api", target_host="example.com", target_port=443, protocol="https-mitm")
        replay = Mock(return_value=(True, "replayed"))
        actions = RuntimeReplayActionService(proxy_base_url="http://127.0.0.1:8080", replay_request=replay)

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
        response_editor = Mock(return_value=(False, "cancelled"))
        config = RuntimeTestContext()
        actions = RuntimeResponseEditActionService(
            modifier,
            config.policy_administration,
            config.configuration,
            response_editor=response_editor,
        )

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
