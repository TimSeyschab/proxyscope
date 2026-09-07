from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True, kw_only=True)
class RuntimeEvent:
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    request_id: int | None = None
    component_id: str | None = None
    event_type: str = field(init=False, default="runtime.event")


@dataclass(frozen=True, kw_only=True)
class RequestObserved(RuntimeEvent):
    method: str
    path: str
    target_host: str | None
    target_port: int | None
    protocol: str
    event_type: str = field(init=False, default="request.observed")


@dataclass(frozen=True, kw_only=True)
class RequestBodyCaptured(RuntimeEvent):
    body_size: int
    body: bytes | None = field(default=None, repr=False)
    event_type: str = field(init=False, default="request.body_captured")


@dataclass(frozen=True, kw_only=True)
class ResponseObserved(RuntimeEvent):
    status_code: int
    reason: str
    body_size: int
    event_type: str = field(init=False, default="response.observed")


@dataclass(frozen=True, kw_only=True)
class ResponseBodyCaptured(RuntimeEvent):
    body_size: int
    body: bytes | None = field(default=None, repr=False)
    event_type: str = field(init=False, default="response.body_captured")


@dataclass(frozen=True, kw_only=True)
class ExchangeCompleted(RuntimeEvent):
    duration_ms: float
    event_type: str = field(init=False, default="exchange.completed")


@dataclass(frozen=True, kw_only=True)
class ResponseEditRequested(RuntimeEvent):
    request_url: str
    method: str
    artifact_id: str | None = None
    event_type: str = field(init=False, default="response_edit.requested")


@dataclass(frozen=True, kw_only=True)
class ResponseEditApplied(RuntimeEvent):
    request_url: str
    applied: bool
    artifact_id: str | None = None
    error: str | None = None
    event_type: str = field(init=False, default="response_edit.applied")


@dataclass(frozen=True, kw_only=True)
class ReplayRequested(RuntimeEvent):
    request_url: str
    artifact_id: str | None = None
    event_type: str = field(init=False, default="replay.requested")


@dataclass(frozen=True, kw_only=True)
class ReplayCompleted(RuntimeEvent):
    request_url: str
    success: bool
    artifact_id: str | None = None
    error: str | None = None
    event_type: str = field(init=False, default="replay.completed")


@dataclass(frozen=True, kw_only=True)
class ArtifactRecorded(RuntimeEvent):
    artifact_id: str
    artifact_type: str
    status: str
    error: str | None = None
    event_type: str = field(init=False, default="artifact.recorded")


@dataclass(frozen=True, kw_only=True)
class MockResponseServed(RuntimeEvent):
    rule_id: str
    scenario_id: str
    status_code: int
    event_type: str = field(init=False, default="mock.response_served")


@dataclass(frozen=True, kw_only=True)
class TrafficRuleApplied(RuntimeEvent):
    rule_id: str
    summary: str
    status_code: int | None = None
    event_type: str = field(init=False, default="traffic_rule.applied")


@dataclass(frozen=True, kw_only=True)
class ComponentEnabled(RuntimeEvent):
    event_type: str = field(init=False, default="component.enabled")


@dataclass(frozen=True, kw_only=True)
class ComponentDisabled(RuntimeEvent):
    event_type: str = field(init=False, default="component.disabled")


@dataclass(frozen=True, kw_only=True)
class RuntimeStateSnapshotRequested(RuntimeEvent):
    event_type: str = field(init=False, default="runtime_state.snapshot_requested")


@dataclass(frozen=True, kw_only=True)
class RuntimeStateSnapshot(RuntimeEvent):
    correlation_id: str
    settings: Mapping[str, object]
    mockserver_configuration: Mapping[str, object]
    event_type: str = field(init=False, default="runtime_state.snapshot")
