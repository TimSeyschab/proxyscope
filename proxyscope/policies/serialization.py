import base64

from proxyscope.policies.matching import normalize_http_method, normalize_policy_url
from proxyscope.policies.models import OpenEditorAction, PolicyRule, RequestMatchRule, StaticResponseAction


def serialize_policy_rule(rule: PolicyRule) -> dict:
    action_type = "open_editor" if isinstance(rule.action, OpenEditorAction) else "static_response"
    payload = {
        "name": rule.name,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "action": {"type": action_type},
        "match": {},
    }
    if rule.match.methods is not None:
        payload["match"]["methods"] = list(rule.match.methods)
    if rule.match.url_exact is not None:
        payload["match"]["url_exact"] = rule.match.url_exact
    if rule.match.url_prefix is not None:
        payload["match"]["url_prefix"] = rule.match.url_prefix

    if isinstance(rule.action, StaticResponseAction):
        payload["action"]["status_code"] = rule.action.status_code
        payload["action"]["reason"] = rule.action.reason
        payload["action"]["headers"] = dict(rule.action.headers)
        try:
            payload["action"]["body"] = rule.action.body.decode("utf-8")
        except UnicodeDecodeError:
            payload["action"]["body_base64"] = base64.b64encode(rule.action.body).decode("ascii")
    return payload


def parse_policy_rule(data: object) -> PolicyRule | None:
    if not isinstance(data, dict):
        return None
    name = str(data.get("name", "unnamed-policy"))
    enabled = bool(data.get("enabled", True))
    priority = int(data.get("priority", 0))

    action_data = data.get("action", {})
    if not isinstance(action_data, dict):
        return None
    action_type = str(action_data.get("type", "")).strip()
    if action_type not in {"open_editor", "static_response"}:
        return None

    match_data = data.get("match", {})
    if not isinstance(match_data, dict):
        return None
    methods_raw = match_data.get("methods")
    methods: tuple[str, ...] | None = None
    if isinstance(methods_raw, list):
        normalized_methods = [normalize_http_method(str(item)) for item in methods_raw]
        methods = tuple(normalized_methods) if normalized_methods else None
    elif isinstance(methods_raw, str):
        methods = (normalize_http_method(methods_raw),)

    url_exact = match_data.get("url_exact")
    url_prefix = match_data.get("url_prefix")
    match = RequestMatchRule(
        methods=methods,
        url_exact=normalize_policy_url(url_exact) if isinstance(url_exact, str) else None,
        url_prefix=normalize_policy_url(url_prefix) if isinstance(url_prefix, str) else None,
    )
    action = OpenEditorAction() if action_type == "open_editor" else _parse_static_response_action(action_data)
    return PolicyRule(name=name, enabled=enabled, priority=priority, action=action, match=match)


def _parse_static_response_action(action_data: dict) -> StaticResponseAction:
    body_base64 = action_data.get("body_base64")
    if isinstance(body_base64, str):
        try:
            body = base64.b64decode(body_base64, validate=True)
        except ValueError:
            body = b""
    else:
        body = str(action_data.get("body", "")).encode("utf-8")
    headers_raw = action_data.get("headers", {})
    return StaticResponseAction(
        status_code=int(action_data.get("status_code", 200)),
        reason=str(action_data.get("reason", "OK")),
        headers=dict(headers_raw) if isinstance(headers_raw, dict) else {},
        body=body,
    )
