from dataclasses import dataclass, field
from typing import TypeAlias


@dataclass(frozen=True)
class RequestMatchRule:
    methods: tuple[str, ...] | None = None
    url_exact: str | None = None
    url_prefix: str | None = None

    def __post_init__(self) -> None:
        if self.url_exact is not None and self.url_prefix is not None:
            raise ValueError("A policy match cannot define both url_exact and url_prefix.")
        if self.methods is not None and not self.methods:
            raise ValueError("Policy match methods must be None or contain at least one method.")


@dataclass(frozen=True)
class OpenEditorAction:
    pass


@dataclass(frozen=True)
class StaticResponseAction:
    status_code: int = 200
    reason: str = "OK"
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def __post_init__(self) -> None:
        if not 100 <= self.status_code <= 599:
            raise ValueError("Static response status code must be between 100 and 599.")


PolicyAction: TypeAlias = OpenEditorAction | StaticResponseAction


@dataclass(frozen=True)
class PolicyRule:
    name: str
    enabled: bool
    priority: int
    action: PolicyAction
    match: RequestMatchRule

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Policy name must not be empty.")
