from dataclasses import dataclass


@dataclass(frozen=True)
class RequestMatchRule:
    methods: tuple[str, ...] | None = None
    url_exact: str | None = None
    url_prefix: str | None = None


@dataclass(frozen=True)
class StaticResponseTemplate:
    status_code: int
    reason: str
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class PolicyRule:
    name: str
    enabled: bool
    action: str  # "open_editor" | "static_response"
    match: RequestMatchRule
    static_response: StaticResponseTemplate | None = None
