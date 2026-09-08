from __future__ import annotations

from threading import RLock
from typing import Protocol, runtime_checkable

from proxyscope.application.artifacts.models import (
    Artifact,
    ArtifactStatus,
    BodyReference,
    ReplayArtifact,
    ResponseEditArtifact,
    StaticResponseArtifact,
)


@runtime_checkable
class ArtifactStore(Protocol):
    def body_reference(self, body: bytes | None) -> BodyReference: ...

    def add(self, artifact: Artifact) -> None: ...

    def replace(self, artifact: Artifact) -> None: ...

    def list_for_source(self, source_request_id: int) -> tuple[Artifact, ...]: ...


class InMemoryArtifactStore:
    def __init__(self, *, max_body_bytes: int = 4096) -> None:
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be greater than zero.")
        self._max_body_bytes = max_body_bytes
        self._lock = RLock()
        self._artifacts: dict[str, Artifact] = {}

    def body_reference(self, body: bytes | None) -> BodyReference:
        return create_body_reference(body, max_body_bytes=self._max_body_bytes)

    def add(self, artifact: Artifact) -> None:
        artifact_id = _artifact_id(artifact)
        with self._lock:
            if artifact_id in self._artifacts:
                raise ValueError(f"Artifact already exists: {artifact_id}")
            self._artifacts[artifact_id] = artifact

    def replace(self, artifact: Artifact) -> None:
        artifact_id = _artifact_id(artifact)
        with self._lock:
            if artifact_id not in self._artifacts:
                raise ValueError(f"Artifact not found: {artifact_id}")
            self._artifacts[artifact_id] = artifact

    def list_for_source(self, source_request_id: int) -> tuple[Artifact, ...]:
        with self._lock:
            return tuple(
                artifact for artifact in self._artifacts.values() if _source_request_id(artifact) == source_request_id
            )


def _artifact_id(artifact: Artifact) -> str:
    if isinstance(artifact, ReplayArtifact):
        return artifact.replay_id
    if isinstance(artifact, ResponseEditArtifact):
        return artifact.edit_id
    return artifact.artifact_id


def _source_request_id(artifact: Artifact) -> int | None:
    return artifact.source_request_id


def create_body_reference(body: bytes | None, *, max_body_bytes: int = 4096) -> BodyReference:
    if max_body_bytes <= 0:
        raise ValueError("max_body_bytes must be greater than zero.")
    value = body or b""
    preview = value[:max_body_bytes]
    return BodyReference(size=len(value), preview=preview, truncated=len(preview) < len(value))


__all__ = [
    "Artifact",
    "ArtifactStatus",
    "ArtifactStore",
    "BodyReference",
    "InMemoryArtifactStore",
    "ReplayArtifact",
    "ResponseEditArtifact",
    "StaticResponseArtifact",
    "create_body_reference",
]
