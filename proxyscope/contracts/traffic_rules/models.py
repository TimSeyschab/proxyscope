from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from proxyscope.contracts.exchanges import ExchangeRequest, ExchangeResponse

MAX_PATTERN_LENGTH = 512
MAX_REPLACEMENT_LENGTH = 8192
MAX_REGEX_MATCHES = 1000


class RulePhase(StrEnum):
    REQUEST = "request"
    RESPOND = "respond"
    RESPONSE = "response"


@dataclass(frozen=True)
class TrafficMatch:
    methods: tuple[str, ...] = ()
    url: str | None = None
    url_prefix: bool = False
    url_regex: bool = False
    host: str | None = None
    status_code: int | None = None
    headers: tuple[tuple[str, str], ...] = ()
    content_type: str | None = None

    def matches_request(self, request: ExchangeRequest) -> bool:
        return (
            self._matches_request_target(request)
            and _headers_match(self.headers, request.headers)
            and _content_type_matches(self.content_type, request.headers)
        )

    def _matches_request_target(self, request: ExchangeRequest) -> bool:
        if self.methods and request.method.upper() not in {method.upper() for method in self.methods}:
            return False
        if self.host is not None and (request.target_host or "").lower() != self.host.lower():
            return False
        return _url_matches(self, request.url)

    def matches_response(self, request: ExchangeRequest, response: ExchangeResponse) -> bool:
        return (
            self._matches_request_target(request)
            and (self.status_code is None or self.status_code == response.status_code)
            and _headers_match(self.headers, response.headers)
            and _content_type_matches(self.content_type, response.headers)
        )


@dataclass(frozen=True)
class RespondAction:
    status_code: int = 200
    reason: str = "OK"
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = b""


@dataclass(frozen=True)
class OpenEditorAction:
    pass


@dataclass(frozen=True)
class RegexBodyRewriteAction:
    pattern: str
    replacement: str
    flags: int = 0
    max_matches: int = MAX_REGEX_MATCHES
    allow_compressed: bool = False

    def __post_init__(self) -> None:
        if not self.pattern or len(self.pattern) > MAX_PATTERN_LENGTH:
            raise ValueError("Regex pattern has an invalid length.")
        if len(self.replacement) > MAX_REPLACEMENT_LENGTH:
            raise ValueError("Regex replacement is too long.")
        if self.max_matches <= 0 or self.max_matches > MAX_REGEX_MATCHES:
            raise ValueError("Regex max_matches is out of range.")
        re.compile(self.pattern, self.flags)


@dataclass(frozen=True)
class HeaderSetAction:
    name: str
    value: str


@dataclass(frozen=True)
class HeaderReplaceAction:
    name: str
    value: str


@dataclass(frozen=True)
class HeaderRemoveAction:
    name: str


TrafficAction = (
    OpenEditorAction
    | RespondAction
    | RegexBodyRewriteAction
    | HeaderSetAction
    | HeaderReplaceAction
    | HeaderRemoveAction
)


@dataclass(frozen=True)
class TrafficRule:
    rule_id: str
    name: str
    enabled: bool
    priority: int
    phase: RulePhase
    match: TrafficMatch
    action: TrafficAction

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.name.strip():
            raise ValueError("Traffic rule ID and name must not be empty.")
        if self.phase is RulePhase.RESPOND and not isinstance(self.action, RespondAction):
            raise ValueError("Respond rules require RespondAction.")
        if self.phase is not RulePhase.RESPOND and isinstance(self.action, RespondAction):
            raise ValueError("RespondAction requires respond phase.")
        if self.phase is not RulePhase.RESPONSE and isinstance(self.action, OpenEditorAction):
            raise ValueError("OpenEditorAction requires response phase.")


def _url_matches(match: TrafficMatch, url: str) -> bool:
    if match.url is None:
        return True
    if match.url_regex:
        return re.fullmatch(match.url, url) is not None
    return url.startswith(match.url) if match.url_prefix else url == match.url


def _headers_match(expected: tuple[tuple[str, str], ...], actual: dict[str, str]) -> bool:
    return all((_header(actual, name) or "") == value for name, value in expected)


def _content_type_matches(expected: str | None, headers: dict[str, str]) -> bool:
    return expected is None or expected.lower() in (_header(headers, "Content-Type") or "").lower()


def _header(headers: dict[str, str], name: str) -> str | None:
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)
