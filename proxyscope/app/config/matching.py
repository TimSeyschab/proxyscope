from dataclasses import dataclass
from urllib.parse import urlsplit

from proxyscope.app.config.models import PolicyRule


def normalize_whitelist_entry(value: str) -> str:
    raw_value = value.strip()
    if not raw_value:
        raise ValueError("Whitelist entry must not be empty.")

    if "://" in raw_value:
        parsed = urlsplit(raw_value)
        host = parsed.hostname
    elif "/" in raw_value:
        parsed = urlsplit(f"http://{raw_value}")
        host = parsed.hostname
    else:
        parsed = urlsplit(f"http://{raw_value}")
        host = parsed.hostname

    if not host:
        raise ValueError(f"Invalid whitelist entry: {value}")
    return host.lower()


def normalize_modification_url(value: str) -> str:
    raw_value = value.strip()
    if not raw_value:
        raise ValueError("Modification URL must not be empty.")

    if "://" not in raw_value:
        raw_value = f"http://{raw_value}"

    parsed = urlsplit(raw_value)
    if not parsed.hostname:
        raise ValueError(f"Invalid modification URL: {value}")

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
    normalized = normalize_modification_url(url)
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
        # Host-wide fallback when configured with "/"
        candidate_parsed = _parse_normalized_modification_url(candidate)
        if url_exact is not None:
            entry = _parse_normalized_modification_url(url_exact)
            if entry.host == candidate_parsed.host and entry.port == candidate_parsed.port:
                if entry.path == "/" or candidate_parsed.path.startswith(entry.path):
                    return True
        if url_prefix is not None:
            entry = _parse_normalized_modification_url(url_prefix)
            if entry.host == candidate_parsed.host and entry.port == candidate_parsed.port:
                if entry.path == "/" or candidate_parsed.path.startswith(entry.path):
                    return True
    return False


def rule_matches_url(rule: PolicyRule, normalized_url: str) -> bool:
    target = rule.match.url_exact or rule.match.url_prefix
    if target is None:
        return False
    return target == normalized_url


def first_rule_method(rule: PolicyRule) -> str | None:
    methods = rule.match.methods
    if not methods:
        return None
    return methods[0]


def rule_method_display(rule: PolicyRule) -> str:
    method = first_rule_method(rule)
    return method or "*"


def rule_url_display(rule: PolicyRule) -> str:
    return rule.match.url_exact or rule.match.url_prefix or "*"


def policy_description(rule: PolicyRule) -> str:
    state = "on" if rule.enabled else "off"
    method = rule_method_display(rule)
    target = rule_url_display(rule)
    if rule.action == "open_editor":
        return f"{rule.name} [{state}] open_editor {method} {target}"
    if rule.action == "static_response" and rule.static_response is not None:
        return (
            f"{rule.name} [{state}] static_response {method} {target} "
            f"-> {rule.static_response.status_code} {rule.static_response.reason}"
        )
    return f"{rule.name} [{state}] {rule.action} {method} {target}"


def _alternate_scheme_url(normalized_url: str) -> str | None:
    parsed = urlsplit(normalized_url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    alternate_scheme = "https" if scheme == "http" else "http"
    return f"{alternate_scheme}://{parsed.netloc}{parsed.path or '/'}"


@dataclass(frozen=True)
class _NormalizedModUrl:
    host: str
    port: int | None
    path: str


def _parse_normalized_modification_url(value: str) -> _NormalizedModUrl:
    parsed = urlsplit(value)
    return _NormalizedModUrl(
        host=(parsed.hostname or "").lower(),
        port=parsed.port,
        path=parsed.path or "/",
    )
