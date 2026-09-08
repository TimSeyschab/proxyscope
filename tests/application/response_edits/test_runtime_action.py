from threading import Event
from unittest.mock import Mock, patch

import pytest

from proxyscope.application.actions.runtime_actions import RuntimeResponseEditActionService
from proxyscope.application.artifacts import ArtifactStatus, InMemoryArtifactStore, ResponseEditArtifact
from proxyscope.application.processing.models import ExchangeResponse
from proxyscope.application.response_edits import PendingResponseEdit, ResponseEditorResult, ResponseModifierService
from proxyscope.contracts.traffic_rules import RespondAction
from tests.support.runtime_context import RuntimeTestContext


def test_successful_edit_persists_rule_with_unambiguous_body_headers() -> None:
    config = RuntimeTestContext()
    modifier = ResponseModifierService()
    pending = PendingResponseEdit(
        request_url="https://api.test/items",
        method="GET",
        response=ExchangeResponse(201, "Created", {}, b"original"),
        _done=Event(),
    )
    edited_headers = {"content-length": "999", "transfer-encoding": "chunked", "X-Edited": "yes"}

    def edit_response(task: PendingResponseEdit) -> ResponseEditorResult:
        task.apply(headers=edited_headers, body=b"edited")
        return ResponseEditorResult(True, "Applied response edits", headers=edited_headers, body=b"edited")

    service = RuntimeResponseEditActionService(
        modifier, config.traffic_rules, config.configuration, response_editor=edit_response
    )
    with patch.object(modifier, "poll_pending_edit", return_value=pending):
        message = service.process_pending_edit()

    assert message == "Applied response edits; saved static traffic rule static-response-1."
    (rule,) = config.traffic_rules.list_rules()
    assert rule.match.url == pending.request_url
    assert isinstance(rule.action, RespondAction)
    assert rule.action.status_code == 201
    assert rule.action.body == b"edited"
    assert dict(rule.action.headers) == {"X-Edited": "yes", "Content-Length": "6"}
    assert pending.wait(timeout_s=0).headers == dict(rule.action.headers)
    assert config.to_config_document().traffic_rules[0]["id"] == rule.rule_id


@pytest.mark.parametrize(
    "result,status",
    [
        (ResponseEditorResult(False, "cancelled"), ArtifactStatus.CANCELLED),
        (ResponseEditorResult(True, "missing headers", headers=None, body=b"edited"), ArtifactStatus.FAILED),
        (ResponseEditorResult(True, "missing body", headers={}, body=None), ArtifactStatus.FAILED),
        (OSError("editor crashed"), ArtifactStatus.FAILED),
    ],
)
def test_failed_or_incomplete_edit_finishes_task_without_saving_rule(result, status):
    config = RuntimeTestContext()
    store = InMemoryArtifactStore()
    modifier = ResponseModifierService(artifact_store=store)
    artifact = ResponseEditArtifact(
        1, "GET", "http://api.test", (), store.body_reference(b"original"), ArtifactStatus.RUNNING
    )
    store.add(artifact)
    pending = PendingResponseEdit(
        artifact.request_url,
        "GET",
        ExchangeResponse(200, "OK", {}, b"original"),
        Event(),
        source_request_id=1,
        artifact=artifact,
    )
    editor = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
    service = RuntimeResponseEditActionService(
        modifier, config.traffic_rules, config.configuration, response_editor=editor
    )
    with patch.object(modifier, "poll_pending_edit", return_value=pending):
        message = service.process_pending_edit()
    assert message
    assert pending.is_done
    assert pending.wait(timeout_s=0) is pending.response
    assert config.traffic_rules.list_rules() == ()
    (recorded,) = store.list_for_source(1)
    assert recorded.status is status
    assert recorded.error


def test_no_pending_edit_does_not_invoke_editor():
    config = RuntimeTestContext()
    editor = Mock()
    service = RuntimeResponseEditActionService(
        ResponseModifierService(),
        config.traffic_rules,
        config.configuration,
        response_editor=editor,
    )
    assert service.process_pending_edit() is None
    editor.assert_not_called()
