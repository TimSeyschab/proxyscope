import unittest
from threading import Event
from unittest.mock import Mock

from proxyscope.application.actions import (
    RuntimePolicyActionService,
    RuntimeReplayActionService,
    RuntimeResponseEditActionService,
)
from proxyscope.application.journal import LoggedExchange, RequestJournal
from proxyscope.application.response_edits import PendingResponseEdit, ResponseEditorResult
from proxyscope.policies.engine import PolicyEngine
from proxyscope.processing.models import ExchangeResponse
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

    def test_static_response_policy_can_be_created_from_captured_response(self) -> None:
        config = RuntimeTestContext()
        configuration = Mock()
        policy_editor = Mock(side_effect=lambda rule: (True, rule, f"Policy updated: {rule.name}"))
        entry = _request_entry_with_response(
            path="/api",
            target_host="example.com",
            target_port=443,
            protocol="https-mitm",
            response_body=b"captured-body",
        )
        actions = RuntimePolicyActionService(
            config.policy_administration,
            configuration,
            policy_editor=policy_editor,
        )

        message = actions.add_static_response_policy_for_request(entry)

        self.assertEqual(message, "Policy updated: static-response-1")
        policy_editor.assert_called_once()
        configuration.save.assert_called_once_with()
        template = PolicyEngine(config.policy_repository).get_static_response_template_for_request(
            method="GET",
            url="https://example.com/api",
        )
        self.assertIsNotNone(template)
        assert template is not None
        self.assertEqual(template.body, b"captured-body")

    def test_cancelled_static_response_policy_edit_discards_created_policy(self) -> None:
        config = RuntimeTestContext()
        configuration = Mock()
        policy_editor = Mock(return_value=(False, None, "cancelled"))
        entry = _request_entry_with_response(
            path="/api",
            target_host="example.com",
            target_port=443,
            protocol="https-mitm",
            response_body=b"captured-body",
        )
        actions = RuntimePolicyActionService(
            config.policy_administration,
            configuration,
            policy_editor=policy_editor,
        )

        message = actions.add_static_response_policy_for_request(entry)

        self.assertEqual(message, "cancelled")
        self.assertEqual(config.policy_rules(), ())
        configuration.save.assert_not_called()

    def test_static_response_policy_rejects_truncated_captured_response(self) -> None:
        config = RuntimeTestContext()
        entry = _request_entry_with_response(
            path="/api",
            target_host="example.com",
            target_port=443,
            protocol="https-mitm",
            response_body=b"partial",
            response_body_size=20,
        )
        actions = RuntimePolicyActionService(
            config.policy_administration,
            config.configuration,
            policy_editor=Mock(),
        )

        message = actions.add_static_response_policy_for_request(entry)

        self.assertEqual(message, "Selected response body was not fully captured.")


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
    def test_successful_pending_edit_saves_static_response_policy(self) -> None:
        pending = PendingResponseEdit(
            request_url="https://example.com/edited",
            method="GET",
            response=ExchangeResponse(
                status_code=200,
                reason="OK",
                headers={"Content-Type": "text/plain"},
                body=b"original",
            ),
            _done=Event(),
        )
        modifier = Mock()
        modifier.poll_pending_edit.return_value = pending
        response_editor = Mock(
            return_value=ResponseEditorResult(
                True,
                "Applied response edits for https://example.com/edited",
                headers={"Content-Type": "text/plain", "Transfer-Encoding": "chunked"},
                body=b"edited-body",
            )
        )
        config = RuntimeTestContext()
        config.add_open_editor_policy("https://example.com/edited", method="GET")
        actions = RuntimeResponseEditActionService(
            modifier,
            config.policy_administration,
            config.configuration,
            response_editor=response_editor,
        )

        message = actions.process_pending_edit()

        self.assertEqual(
            message,
            "Applied response edits for https://example.com/edited; saved static policy static-response-2.",
        )
        template = PolicyEngine(config.policy_repository).get_static_response_template_for_request(
            method="GET",
            url="https://example.com/edited",
        )
        self.assertIsNotNone(template)
        assert template is not None
        self.assertEqual(template.body, b"edited-body")
        self.assertEqual(template.headers["Content-Length"], "11")
        self.assertNotIn("Transfer-Encoding", template.headers)
        self.assertFalse(
            PolicyEngine(config.policy_repository).should_modify_response_for_request(
                method="GET",
                url="https://example.com/edited",
            )
        )

    def test_failed_pending_edit_keeps_original_response(self) -> None:
        pending = Mock()
        modifier = Mock()
        modifier.poll_pending_edit.return_value = pending
        response_editor = Mock(return_value=ResponseEditorResult(False, "cancelled"))
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

    def test_failed_pending_edit_does_not_save_static_response_policy(self) -> None:
        pending = Mock()
        modifier = Mock()
        modifier.poll_pending_edit.return_value = pending
        response_editor = Mock(return_value=ResponseEditorResult(False, "cancelled"))
        config = RuntimeTestContext()
        actions = RuntimeResponseEditActionService(
            modifier,
            config.policy_administration,
            config.configuration,
            response_editor=response_editor,
        )

        actions.process_pending_edit()

        self.assertEqual(config.policy_rules(), ())


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


def _request_entry_with_response(
    *,
    path: str,
    target_host: str | None,
    target_port: int | None,
    protocol: str,
    response_body: bytes,
    response_body_size: int | None = None,
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
    journal.complete_request(
        request_id,
        status_code=200,
        reason="OK",
        start_line="HTTP/1.1 200 OK",
        headers={"Content-Type": "text/plain"},
        body=response_body,
        duration_ms=1.0,
        body_size=response_body_size,
    )
    entry = journal.get_entry(request_id)
    assert entry is not None
    return entry


if __name__ == "__main__":
    unittest.main()
