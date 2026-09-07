from __future__ import annotations

import re
from dataclasses import replace

from proxyscope.application.events import EventBus, TrafficRuleApplied
from proxyscope.application.processing.headers import header_value, headers_for_body
from proxyscope.application.processing.models import ExchangeRequest, ExchangeResponse
from proxyscope.contracts.traffic_rules import (
    HeaderRemoveAction,
    HeaderReplaceAction,
    HeaderSetAction,
    OpenEditorAction,
    RegexBodyRewriteAction,
    RespondAction,
    RulePhase,
    TrafficAction,
)

from .store import TrafficRuleStore
from proxyscope.contracts.traffic_rules import TrafficRule


class TrafficRuleEngine:
    def __init__(
        self,
        store: TrafficRuleStore | None = None,
        *,
        event_bus: EventBus | None = None,
    ) -> None:
        self.store = store or TrafficRuleStore()
        self._event_bus = event_bus

    def prepare_request(self, request: ExchangeRequest) -> tuple[ExchangeRequest, ExchangeResponse | None]:
        processed = request
        for rule in self._rules(RulePhase.REQUEST):
            if not rule.match.matches_request(processed):
                continue
            updated = _apply_request_action(processed, rule.action)
            if updated != processed:
                processed = updated
                self._publish(rule, None, "request modified")
        for rule in self._rules(RulePhase.RESPOND):
            if rule.match.matches_request(processed):
                action = rule.action
                assert isinstance(action, RespondAction)
                response = ExchangeResponse(
                    action.status_code,
                    action.reason,
                    headers_for_body(dict(action.headers), action.body),
                    action.body,
                    body_size=len(action.body),
                )
                self._publish(rule, None, "static response", status_code=action.status_code)
                return processed, response
        return processed, None

    def process_response(
        self,
        request: ExchangeRequest,
        response: ExchangeResponse,
        *,
        request_id: int | None,
    ) -> ExchangeResponse:
        processed = response
        for rule in self._rules(RulePhase.RESPONSE):
            if not rule.match.matches_response(request, processed):
                continue
            updated = _apply_response_action(processed, rule.action)
            if updated != processed:
                processed = updated
                self._publish(rule, request_id, "response modified")
        return processed

    def requires_buffered_response(self, request: ExchangeRequest) -> bool:
        return any(
            isinstance(rule.action, OpenEditorAction) and rule.match.matches_request(request)
            for rule in self._rules(RulePhase.RESPONSE)
        )

    def should_open_editor(self, request: ExchangeRequest, response: ExchangeResponse) -> bool:
        return any(
            isinstance(rule.action, OpenEditorAction) and rule.match.matches_response(request, response)
            for rule in self._rules(RulePhase.RESPONSE)
        )

    def _rules(self, phase: RulePhase) -> tuple[TrafficRule, ...]:
        return tuple(rule for rule in self.store.list(scoped=True) if rule.phase is phase)

    def _publish(
        self, rule: TrafficRule, request_id: int | None, summary: str, *, status_code: int | None = None
    ) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(
                TrafficRuleApplied(
                    request_id=request_id, rule_id=rule.rule_id, summary=summary, status_code=status_code
                )
            )


def _apply_request_action(request: ExchangeRequest, action: TrafficAction) -> ExchangeRequest:
    if isinstance(action, RegexBodyRewriteAction):
        body = _rewrite_body(request.body, request.headers, action)
        return request if body is None else replace(request, body=body, headers=headers_for_body(request.headers, body))
    if isinstance(action, (HeaderSetAction, HeaderReplaceAction, HeaderRemoveAction)):
        return replace(request, headers=_apply_headers(request.headers, action))
    return request


def _apply_response_action(response: ExchangeResponse, action: TrafficAction) -> ExchangeResponse:
    if isinstance(action, RegexBodyRewriteAction):
        body = _rewrite_body(response.body, response.headers, action)
        return (
            response
            if body is None
            else replace(response, body=body, headers=headers_for_body(response.headers, body), body_size=len(body))
        )
    if isinstance(action, (HeaderSetAction, HeaderReplaceAction, HeaderRemoveAction)):
        return replace(response, headers=_apply_headers(response.headers, action))
    return response


def _rewrite_body(body: bytes, headers: dict[str, str], action: RegexBodyRewriteAction) -> bytes | None:
    if header_value(headers, "Content-Encoding") and not action.allow_compressed:
        return None
    if not _is_textual(headers):
        return None
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    rewritten, count = re.subn(action.pattern, action.replacement, text, count=action.max_matches, flags=action.flags)
    return None if count == 0 else rewritten.encode("utf-8")


def _apply_headers(
    headers: dict[str, str], action: HeaderSetAction | HeaderReplaceAction | HeaderRemoveAction
) -> dict[str, str]:
    updated = dict(headers)
    existing = next((name for name in updated if name.lower() == action.name.lower()), None)
    if isinstance(action, HeaderRemoveAction):
        if existing is not None:
            del updated[existing]
        return updated
    if isinstance(action, HeaderSetAction) and existing is not None:
        return updated
    if isinstance(action, HeaderReplaceAction) and existing is None:
        return updated
    if existing is not None:
        del updated[existing]
    updated[action.name] = action.value
    return updated


def _is_textual(headers: dict[str, str]) -> bool:
    content_type = (header_value(headers, "Content-Type") or "").lower()
    return content_type.startswith("text/") or any(
        token in content_type for token in ("json", "xml", "javascript", "form-urlencoded")
    )
