from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4


class ArtifactStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    APPLIED = "applied"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class BodyReference:
    size: int
    preview: bytes
    truncated: bool


@dataclass(frozen=True)
class ReplayArtifact:
    source_request_id: int
    method: str
    url: str
    headers: tuple[tuple[str, str], ...]
    body: BodyReference
    status: ArtifactStatus = ArtifactStatus.DRAFT
    error: str | None = None
    replay_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class ResponseEditArtifact:
    source_request_id: int | None
    method: str
    request_url: str
    headers: tuple[tuple[str, str], ...]
    body: BodyReference
    status: ArtifactStatus = ArtifactStatus.DRAFT
    error: str | None = None
    edit_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class StaticResponseArtifact:
    source_request_id: int
    rule_id: str
    method: str
    url: str
    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: BodyReference
    status: ArtifactStatus = ArtifactStatus.APPLIED
    error: str | None = None
    artifact_id: str = field(default_factory=lambda: str(uuid4()))


Artifact = ReplayArtifact | ResponseEditArtifact | StaticResponseArtifact

__all__ = [
    "Artifact",
    "ArtifactStatus",
    "BodyReference",
    "ReplayArtifact",
    "ResponseEditArtifact",
    "StaticResponseArtifact",
]
