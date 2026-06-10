from dataclasses import dataclass
from urllib.parse import urlsplit

from proxyscope.policies.models import OpenEditorAction, PolicyRule, StaticResponseAction


def normalize_policy_url(value: str) -> str:
    raw_value = value.strip()
    if not raw_value:
        raise ValueError("Policy URL must not be empty.")
    if "://" not in raw_value:
        raw_value = f"http://{raw_value}"

    parsed = urlsplit(raw_value)
    if not parsed.hostname:
        raise ValueError(f"Invalid policy URL: {value}")

    scheme = parsed.scheme.lower() or "http"
    host = parsed.hostname.lower()
    port = parsed.port
    path = parsed.path or "/"
    normalized_path = path if path.startswith("/") else f"/{path}"
    netloc = f"{host}:{port}" if port is not None else host
    return f"{scheme}://{netloc}{normalized_path}"


def normalize_http_method(method: str | None) -> str:
    if method is None:
        raise ValueError("HTTP method must not be empty.")
    normalized = method.strip().upper()
    if not normalized:
        raise ValueError("HTTP method must not be empty.")
    return normalized


def request_url_candidates(url: str) -> tuple[str, ...]:
    normalized = normalize_policy_url(url)
    alternate = _alternate_scheme_url(normalized)
    if alternate is None:
        return (normalized,)
    return (normalized, alternate)


def policy_rule_matches_request(*, rule: PolicyRule, method: str, url_candidates: tuple[str, ...]) -> bool:
    methods = rule.match.methods
    if methods is not None and method not in methods:
        return False

    url_exact = rule.match.url_exact
    url_prefix = rule.match.url_prefix
    if url_exact is None and url_prefix is None:
        return True

    for candidate in url_candidates:
        if url_exact is not None and candidate == url_exact:
            return True
        if url_prefix is not None and candidate.startswith(url_prefix):
            return True
        candidate_parsed = _parse_normalized_policy_url(candidate)
        target = url_exact or url_prefix
        if target is not None:
            entry = _parse_normalized_policy_url(target)
            if entry.host == candidate_parsed.host and entry.port == candidate_parsed.port:
                if entry.path == "/" or candidate_parsed.path.startswith(entry.path):
                    return True
    return False


def rule_matches_url(rule: PolicyRule, normalized_url: str) -> bool:
    target = rule.match.url_exact or rule.match.url_prefix
    return target is not None and target == normalized_url


def first_rule_method(rule: PolicyRule) -> str | None:
    methods = rule.match.methods
    return methods[0] if methods else None


def rule_method_display(rule: PolicyRule) -> str:
    return first_rule_method(rule) or "*"


def rule_url_display(rule: PolicyRule) -> str:
    return rule.match.url_exact or rule.match.url_prefix or "*"


def policy_description(rule: PolicyRule) -> str:
    state = "on" if rule.enabled else "off"
    method = rule_method_display(rule)
    target = rule_url_display(rule)
    if isinstance(rule.action, OpenEditorAction):
        return f"{rule.name} [{state}] prio={rule.priority} open_editor {method} {target}"
    action = rule.action
    return (
        f"{rule.name} [{state}] prio={rule.priority} static_response {method} {target} "
        f"-> {action.status_code} {action.reason}"
    )


def policy_sort_key(rule: PolicyRule) -> tuple[int, int, int, int]:
    target = rule_url_display(rule)
    is_exact = 1 if rule.match.url_exact is not None else 0
    static_precedence = 1 if isinstance(rule.action, StaticResponseAction) else 0
    return (rule.priority, is_exact, len(target), static_precedence)


def _alternate_scheme_url(normalized_url: str) -> str | None:
    parsed = urlsplit(normalized_url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    alternate_scheme = "https" if scheme == "http" else "http"
    return f"{alternate_scheme}://{parsed.netloc}{parsed.path or '/'}"


@dataclass(frozen=True)
class _NormalizedPolicyUrl:
    host: str
    port: int | None
    path: str


def _parse_normalized_policy_url(value: str) -> _NormalizedPolicyUrl:
    parsed = urlsplit(value)
    return _NormalizedPolicyUrl(host=(parsed.hostname or "").lower(), port=parsed.port, path=parsed.path or "/")
