import json
import logging
from http import HTTPStatus

from proxyscope.config.migrations import CURRENT_SCHEMA_VERSION, migrate_config_payload
from proxyscope.config.settings import ConfigDocument, RuntimeSettings
from proxyscope.policies.matching import normalize_http_method, normalize_policy_url
from proxyscope.policies.models import OpenEditorAction, PolicyRule, RequestMatchRule, StaticResponseAction
from proxyscope.policies.serialization import parse_policy_rule, serialize_policy_rule


class ConfigValidationError(ValueError):
    pass


def parse_config_payload(payload: object) -> ConfigDocument:
    migrated = migrate_config_payload(payload)
    _reject_unknown_fields(migrated, {"schema_version", "settings", "policies", "policy_shortcuts"}, "config")
    settings = _parse_settings(migrated.get("settings"))
    policies = _parse_policies(migrated.get("policies", []))
    shortcuts = _parse_policy_shortcuts(migrated.get("policy_shortcuts", []))
    return ConfigDocument(settings=settings, policies=policies + shortcuts)


def serialize_config_document(document: ConfigDocument) -> dict:
    settings = document.settings
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "settings": {
            "log_level": logging.getLevelName(settings.log_level),
            "log_whitelist": list(settings.log_whitelist),
            "cache_invalidation_enabled": settings.cache_invalidation_enabled,
            "mitm_enabled": settings.mitm_enabled,
            "mitm_certs_dir": str(settings.mitm_certs_dir),
        },
        "policies": [serialize_policy_rule(rule) for rule in document.policies],
    }


def _parse_settings(value: object) -> RuntimeSettings:
    if not isinstance(value, dict):
        raise ConfigValidationError("settings must be a JSON object.")
    _reject_unknown_fields(
        value,
        {"log_level", "log_whitelist", "cache_invalidation_enabled", "mitm_enabled", "mitm_certs_dir"},
        "settings",
    )
    level_name = _required_string(value.get("log_level", "INFO"), "settings.log_level").upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        raise ConfigValidationError(f"settings.log_level has unsupported value: {level_name}")
    whitelist = value.get("log_whitelist", [])
    if not isinstance(whitelist, list) or not all(isinstance(item, str) for item in whitelist):
        raise ConfigValidationError("settings.log_whitelist must be an array of strings.")
    return RuntimeSettings.create(
        log_level=level,
        log_whitelist=whitelist,
        cache_invalidation_enabled=_required_bool(
            value.get("cache_invalidation_enabled", True), "settings.cache_invalidation_enabled"
        ),
        mitm_enabled=_required_bool(value.get("mitm_enabled", True), "settings.mitm_enabled"),
        mitm_certs_dir=_required_string(value.get("mitm_certs_dir", "certs"), "settings.mitm_certs_dir"),
    )


def _parse_policies(value: object) -> tuple[PolicyRule, ...]:
    if not isinstance(value, list):
        raise ConfigValidationError("policies must be an array.")
    rules: list[PolicyRule] = []
    for index, item in enumerate(value):
        _validate_canonical_policy_shape(item, index)
        try:
            rule = parse_policy_rule(item)
        except (TypeError, ValueError) as exc:
            raise ConfigValidationError(f"policies[{index}] is invalid: {exc}") from exc
        if rule is None:
            raise ConfigValidationError(f"policies[{index}] is invalid or has an unsupported action.")
        rules.append(rule)
    return tuple(rules)


def _validate_canonical_policy_shape(value: object, index: int) -> None:
    field = f"policies[{index}]"
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{field} must be a JSON object.")
    _reject_unknown_fields(value, {"name", "enabled", "priority", "action", "match"}, field)
    if "name" in value:
        _required_string(value["name"], f"{field}.name")
    if "enabled" in value:
        _required_bool(value["enabled"], f"{field}.enabled")
    if "priority" in value:
        _required_int(value["priority"], f"{field}.priority")
    action = value.get("action")
    if not isinstance(action, dict):
        raise ConfigValidationError(f"{field}.action must be a JSON object.")
    action_type = _required_string(action.get("type"), f"{field}.action.type")
    allowed_action_fields = (
        {"type"}
        if action_type == "open_editor"
        else {"type", "status_code", "reason", "headers", "body", "body_base64"}
    )
    _reject_unknown_fields(action, allowed_action_fields, f"{field}.action")
    match = value.get("match", {})
    if not isinstance(match, dict):
        raise ConfigValidationError(f"{field}.match must be a JSON object.")
    _reject_unknown_fields(match, {"methods", "url_exact", "url_prefix"}, f"{field}.match")


def _parse_policy_shortcuts(value: object) -> tuple[PolicyRule, ...]:
    if not isinstance(value, list):
        raise ConfigValidationError("policy_shortcuts must be an array.")
    return tuple(_parse_policy_shortcut(item, index) for index, item in enumerate(value))


def _parse_policy_shortcut(value: object, index: int) -> PolicyRule:
    field = f"policy_shortcuts[{index}]"
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{field} must be a JSON object.")
    _reject_unknown_fields(value, {"name", "match", "action", "respond", "priority", "enabled"}, field)
    match_text = _required_string(value.get("match"), f"{field}.match")
    method, url, is_prefix = _parse_shortcut_match(match_text, field)
    action_name = value.get("action")
    respond = value.get("respond")
    if (action_name is None) == (respond is None):
        raise ConfigValidationError(f"{field} must define exactly one of action or respond.")
    if action_name is not None:
        if action_name != "open_editor":
            raise ConfigValidationError(f"{field}.action must be 'open_editor'.")
        action = OpenEditorAction()
    else:
        action = _parse_shortcut_response(respond, field)
    return PolicyRule(
        name=_required_string(value.get("name", f"shortcut-{index + 1}"), f"{field}.name"),
        enabled=_required_bool(value.get("enabled", True), f"{field}.enabled"),
        priority=_required_int(value.get("priority", 0), f"{field}.priority"),
        action=action,
        match=RequestMatchRule(
            methods=(method,),
            url_exact=None if is_prefix else url,
            url_prefix=url if is_prefix else None,
        ),
    )


def _parse_shortcut_match(value: str, field: str) -> tuple[str, str, bool]:
    parts = value.split(maxsplit=1)
    if len(parts) != 2:
        raise ConfigValidationError(f"{field}.match must use '<METHOD> <URL>' syntax.")
    method = normalize_http_method(parts[0])
    raw_url = parts[1]
    is_prefix = raw_url.endswith("*")
    url = normalize_policy_url(raw_url[:-1] if is_prefix else raw_url)
    return method, url, is_prefix


def _parse_shortcut_response(value: object, field: str) -> StaticResponseAction:
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{field}.respond must be a JSON object.")
    _reject_unknown_fields(value, {"status", "reason", "headers", "body", "json"}, f"{field}.respond")
    if "body" in value and "json" in value:
        raise ConfigValidationError(f"{field}.respond must not define both body and json.")
    headers_value = value.get("headers", {})
    if not isinstance(headers_value, dict) or not all(
        isinstance(name, str) and isinstance(header_value, str) for name, header_value in headers_value.items()
    ):
        raise ConfigValidationError(f"{field}.respond.headers must be an object of string values.")
    headers = dict(headers_value)
    if "json" in value:
        body = json.dumps(value["json"], ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    else:
        body = _required_string(value.get("body", ""), f"{field}.respond.body").encode("utf-8")
    status_code = _required_int(value.get("status", 200), f"{field}.respond.status")
    reason = value.get("reason")
    if reason is None:
        try:
            reason = HTTPStatus(status_code).phrase
        except ValueError:
            reason = "OK"
    return StaticResponseAction(
        status_code=status_code,
        reason=_required_string(reason, f"{field}.respond.reason"),
        headers=headers,
        body=body,
    )


def _reject_unknown_fields(value: dict, allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConfigValidationError(f"{field} contains unknown field(s): {', '.join(unknown)}.")


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigValidationError(f"{field} must be a non-empty string.")
    return value.strip()


def _required_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigValidationError(f"{field} must be a boolean.")
    return value


def _required_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigValidationError(f"{field} must be an integer.")
    return value
