import base64

from .models import (
    MAX_REGEX_MATCHES,
    HeaderRemoveAction,
    HeaderReplaceAction,
    HeaderSetAction,
    OpenEditorAction,
    RegexBodyRewriteAction,
    RespondAction,
    RulePhase,
    TrafficAction,
    TrafficMatch,
    TrafficRule,
)


def serialize_rule(rule: TrafficRule) -> dict[str, object]:
    action: dict[str, object]
    if isinstance(rule.action, OpenEditorAction):
        action = {"type": "open_editor"}
    elif isinstance(rule.action, RespondAction):
        action = {
            "type": "respond",
            "status": rule.action.status_code,
            "reason": rule.action.reason,
            "headers": dict(rule.action.headers),
            "body_base64": base64.b64encode(rule.action.body).decode("ascii"),
        }
    elif isinstance(rule.action, RegexBodyRewriteAction):
        action = {
            "type": "rewrite_body",
            "pattern": rule.action.pattern,
            "replacement": rule.action.replacement,
            "flags": rule.action.flags,
            "max_matches": rule.action.max_matches,
            "allow_compressed": rule.action.allow_compressed,
        }
    elif isinstance(rule.action, HeaderSetAction):
        action = {"type": "set_header", "name": rule.action.name, "value": rule.action.value}
    elif isinstance(rule.action, HeaderReplaceAction):
        action = {"type": "replace_header", "name": rule.action.name, "value": rule.action.value}
    else:
        action = {"type": "remove_header", "name": rule.action.name}
    return {
        "id": rule.rule_id,
        "name": rule.name,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "phase": rule.phase.value,
        "match": _serialize_match(rule.match),
        "action": action,
    }


def parse_rule(value: dict[str, object]) -> TrafficRule:
    match_value = value.get("match", {})
    action_value = value.get("action", {})
    if not isinstance(match_value, dict) or not isinstance(action_value, dict):
        raise ValueError("Traffic rule match and action must be objects.")
    action = _parse_action(action_value)
    return TrafficRule(
        rule_id=str(value["id"]),
        name=str(value.get("name", value["id"])),
        enabled=bool(value.get("enabled", True)),
        priority=int(str(value.get("priority", 0))),
        phase=RulePhase(str(value["phase"])),
        match=_parse_match(match_value),
        action=action,
    )


def _serialize_match(match: TrafficMatch) -> dict[str, object]:
    return {
        "methods": list(match.methods),
        "url": match.url,
        "prefix": match.url_prefix,
        "regex": match.url_regex,
        "host": match.host,
        "status": match.status_code,
        "headers": dict(match.headers),
        "content_type": match.content_type,
    }


def _parse_match(value: dict[str, object]) -> TrafficMatch:
    methods = value.get("methods", [])
    headers = value.get("headers", {})
    return TrafficMatch(
        methods=tuple(str(item) for item in methods) if isinstance(methods, list) else (),
        url=None if value.get("url") is None else str(value["url"]),
        url_prefix=bool(value.get("prefix", False)),
        url_regex=bool(value.get("regex", False)),
        host=None if value.get("host") is None else str(value["host"]),
        status_code=None if value.get("status") is None else int(str(value["status"])),
        headers=tuple(dict(headers).items()) if isinstance(headers, dict) else (),
        content_type=None if value.get("content_type") is None else str(value["content_type"]),
    )


def _parse_action(value: dict[str, object]) -> TrafficAction:
    action_type = str(value.get("type", ""))
    if action_type == "open_editor":
        return OpenEditorAction()
    if action_type == "respond":
        raw_headers = value.get("headers", {})
        return RespondAction(
            int(str(value.get("status", 200))),
            str(value.get("reason", "OK")),
            tuple(dict(raw_headers).items()) if isinstance(raw_headers, dict) else (),
            base64.b64decode(str(value.get("body_base64", ""))),
        )
    if action_type == "rewrite_body":
        return RegexBodyRewriteAction(
            str(value["pattern"]),
            str(value.get("replacement", "")),
            int(str(value.get("flags", 0))),
            int(str(value.get("max_matches", MAX_REGEX_MATCHES))),
            bool(value.get("allow_compressed", False)),
        )
    if action_type == "set_header":
        return HeaderSetAction(str(value["name"]), str(value["value"]))
    if action_type == "replace_header":
        return HeaderReplaceAction(str(value["name"]), str(value["value"]))
    if action_type == "remove_header":
        return HeaderRemoveAction(str(value["name"]))
    raise ValueError(f"Unsupported traffic rule action: {action_type}")
