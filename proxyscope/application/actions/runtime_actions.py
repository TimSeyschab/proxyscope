from contextlib import nullcontext
from dataclasses import replace
from typing import Callable

from proxyscope.application.artifacts import ArtifactStatus, ArtifactStore, InMemoryArtifactStore, ReplayArtifact
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.contracts import SuspendUI
from proxyscope.application.events import EventBus, ReplayCompleted, ReplayRequested
from proxyscope.application.journal import LoggedExchange
from proxyscope.application.processing.headers import headers_for_body
from proxyscope.application.response_edits import PendingResponseEdit, ResponseEditorResult, ResponseModifierService
from proxyscope.application.traffic_rules import TrafficRuleAdministrationService
from proxyscope.contracts.traffic_rules import RespondAction, RulePhase, TrafficMatch, TrafficRule

ReplayRequest = Callable[..., tuple[bool, str]]
ResponseEditor = Callable[..., ResponseEditorResult]


class RuntimeReplayActionService:
    def __init__(
        self,
        *,
        proxy_base_url: str | None,
        replay_request: ReplayRequest,
        event_bus: EventBus | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._proxy_base_url = proxy_base_url
        self._replay_request = replay_request
        self._event_bus = event_bus
        self._artifact_store = artifact_store or InMemoryArtifactStore()

    def replay(self, entry: LoggedExchange, *, suspend_ui: SuspendUI | None = None) -> str:
        request_url = entry_to_url(entry)
        if request_url is None:
            return "Cannot build URL from selected request."
        artifact = ReplayArtifact(
            source_request_id=entry.request_id,
            method=entry.request.method,
            url=request_url,
            headers=entry.request.headers,
            body=self._artifact_store.body_reference(entry.request.body),
            status=ArtifactStatus.RUNNING,
        )
        self._artifact_store.add(artifact)
        if self._event_bus is not None:
            self._event_bus.publish(ReplayRequested(request_id=entry.request_id, request_url=request_url, artifact_id=artifact.replay_id))
        try:
            with _suspend_runtime_ui(suspend_ui):
                success, message = self._replay_request(entry, request_url=request_url, proxy_base_url=self._proxy_base_url)
            completed = replace(artifact, status=ArtifactStatus.APPLIED if success else ArtifactStatus.FAILED, error=None if success else message)
            self._artifact_store.replace(completed)
            if self._event_bus is not None:
                self._event_bus.publish(ReplayCompleted(request_id=entry.request_id, request_url=request_url, success=success, artifact_id=artifact.replay_id, error=completed.error))
            return message
        except Exception as exc:  # noqa: BLE001
            self._artifact_store.replace(replace(artifact, status=ArtifactStatus.FAILED, error=str(exc)))
            return f"Replay failed ({exc})."


class RuntimeResponseEditActionService:
    def __init__(
        self,
        response_modifier: ResponseModifierService,
        traffic_rules: TrafficRuleAdministrationService,
        configuration: RuntimeConfigurationService,
        *,
        response_editor: ResponseEditor,
        event_bus: EventBus | None = None,
    ) -> None:
        self._response_modifier = response_modifier
        self._traffic_rules = traffic_rules
        self._configuration = configuration
        self._response_editor = response_editor
        self._event_bus = event_bus

    def process_pending_edit(self, *, suspend_ui: SuspendUI | None = None) -> str | None:
        pending = self._response_modifier.poll_pending_edit()
        if pending is None:
            return None
        try:
            with _suspend_runtime_ui(suspend_ui):
                result = self._response_editor(pending)
            if not result.success:
                pending.keep_original()
                self._response_modifier.record_artifact_result(pending, status=ArtifactStatus.CANCELLED, error=result.message)
                return result.message
            if result.headers is None or result.body is None:
                self._response_modifier.record_artifact_result(pending, status=ArtifactStatus.FAILED, error=result.message)
                return result.message
            rule_id = self._save_static_response_rule(pending=pending, headers=result.headers, body=result.body)
            self._response_modifier.record_artifact_result(pending, status=ArtifactStatus.APPLIED, headers=result.headers, body=result.body)
            return f"{result.message}; saved static traffic rule {rule_id}."
        except Exception as exc:  # noqa: BLE001
            pending.keep_original()
            self._response_modifier.record_artifact_result(pending, status=ArtifactStatus.FAILED, error=str(exc))
            return f"Response edit failed ({exc}); kept original response."

    def _save_static_response_rule(self, *, pending: PendingResponseEdit, headers: dict[str, str], body: bytes) -> str:
        existing = {rule.rule_id for rule in self._traffic_rules.list_rules()}
        index = 1
        while f"static-response-{index}" in existing:
            index += 1
        rule_id = f"static-response-{index}"
        response_headers = headers_for_body(headers, body)
        self._traffic_rules.add_rule(
            TrafficRule(
                rule_id=rule_id,
                name=rule_id,
                enabled=True,
                priority=0,
                phase=RulePhase.RESPOND,
                match=TrafficMatch(methods=(pending.method,), url=pending.request_url),
                action=RespondAction(pending.response.status_code, pending.response.reason, tuple(response_headers.items()), body),
            )
        )
        return rule_id


def entry_to_url(entry: LoggedExchange) -> str | None:
    if not entry.target_host:
        return None
    if entry.request.path.startswith(("http://", "https://")):
        return entry.request.path
    path = entry.request.path if entry.request.path.startswith("/") else f"/{entry.request.path}"
    scheme = "https" if entry.protocol.startswith("https") else "http"
    default_port = 443 if scheme == "https" else 80
    port = "" if entry.target_port in (None, default_port) else f":{entry.target_port}"
    return f"{scheme}://{entry.target_host}{port}{path}"


def _suspend_runtime_ui(suspend_ui: SuspendUI | None):
    return suspend_ui() if suspend_ui is not None else nullcontext()
