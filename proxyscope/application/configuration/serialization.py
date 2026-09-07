import logging

from proxyscope.application.configuration.component_settings import ComponentSettings
from proxyscope.application.configuration.models import ConfigDocument, EventStoreSettings, RuntimeSettings
from proxyscope.application.traffic_rules import parse_rule

CURRENT_SCHEMA_VERSION = 1


class ConfigValidationError(ValueError):
    pass


def parse_config_payload(payload: object) -> ConfigDocument:
    if not isinstance(payload, dict):
        raise ConfigValidationError("Config root must be a JSON object.")
    _reject_unknown_fields(payload, {"schema_version", "settings", "event_store", "traffic_rules", "components"}, "config")
    if payload.get("schema_version") != CURRENT_SCHEMA_VERSION:
        raise ConfigValidationError(
            f"Unsupported schema_version {payload.get('schema_version')!r}; expected {CURRENT_SCHEMA_VERSION}."
        )
    return ConfigDocument(
        settings=_parse_settings(payload.get("settings")),
        event_store=_parse_event_store(payload.get("event_store", {}), "event_store"),
        traffic_rules=_parse_traffic_rules(payload.get("traffic_rules", []), "traffic_rules"),
        components=_parse_components(payload.get("components", {})),
    )


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
        "event_store": _serialize_event_store(document.event_store),
        "traffic_rules": list(document.traffic_rules),
        "components": {
            "enabled": list(document.components.enabled_components),
            "configurations": {identifier: value for identifier, value in document.components.configurations},
        },
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


def _parse_components(value: object) -> ComponentSettings:
    if not isinstance(value, dict):
        raise ConfigValidationError("components must be a JSON object.")
    _reject_unknown_fields(value, {"enabled", "configurations"}, "components")
    enabled = value.get("enabled", ["core"])
    if not isinstance(enabled, list) or not all(isinstance(item, str) and item.strip() for item in enabled):
        raise ConfigValidationError("components.enabled must be an array of non-empty strings.")
    configurations = value.get("configurations", {})
    if not isinstance(configurations, dict):
        raise ConfigValidationError("components.configurations must be a JSON object.")
    component_configurations: list[tuple[str, dict[str, object]]] = []
    for component_id, configuration in configurations.items():
        if not isinstance(component_id, str) or not _is_component_id(component_id):
            raise ConfigValidationError("components.configurations keys must be normalized component IDs.")
        if not isinstance(configuration, dict):
            raise ConfigValidationError(f"components.configurations.{component_id} must be a JSON object.")
        if not _is_json_value(configuration):
            raise ConfigValidationError(f"components.configurations.{component_id} must contain JSON values.")
        component_configurations.append((component_id, dict(configuration)))
    return ComponentSettings(
        enabled_components=tuple(dict.fromkeys(item.strip().lower() for item in enabled)),
        configurations=tuple(component_configurations),
    )


def _parse_traffic_rules(value: object, field: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ConfigValidationError(f"{field} must be an array of objects.")
    for index, rule in enumerate(value):
        try:
            parse_rule(rule)
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigValidationError(f"{field}[{index}] is invalid: {exc}") from exc
    return tuple(dict(item) for item in value)


def _parse_event_store(value: object, field: str) -> EventStoreSettings:
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{field} must be a JSON object.")
    _reject_unknown_fields(
        value,
        {"enabled", "path", "max_body_bytes", "max_events", "max_age_days", "max_storage_bytes", "queue_size"},
        field,
    )
    return EventStoreSettings.create(
        enabled=_required_bool(value.get("enabled", False), f"{field}.enabled"),
        path=_required_string(value.get("path", ".proxyscope/events.sqlite3"), f"{field}.path"),
        max_body_bytes=_positive_int(value.get("max_body_bytes", 4096), f"{field}.max_body_bytes"),
        max_events=_optional_positive_int(value.get("max_events"), f"{field}.max_events"),
        max_age_days=_optional_positive_int(value.get("max_age_days"), f"{field}.max_age_days"),
        max_storage_bytes=_optional_positive_int(value.get("max_storage_bytes"), f"{field}.max_storage_bytes"),
        queue_size=_positive_int(value.get("queue_size", 128), f"{field}.queue_size"),
    )


def _serialize_event_store(settings: EventStoreSettings) -> dict[str, object]:
    return {
        "enabled": settings.enabled,
        "path": str(settings.path),
        "max_body_bytes": settings.max_body_bytes,
        "max_events": settings.max_events,
        "max_age_days": settings.max_age_days,
        "max_storage_bytes": settings.max_storage_bytes,
        "queue_size": settings.queue_size,
    }


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


def _positive_int(value: object, field: str) -> int:
    integer = _required_int(value, field)
    if integer <= 0:
        raise ConfigValidationError(f"{field} must be greater than zero.")
    return integer


def _optional_positive_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field)


def _is_component_id(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        bool(normalized)
        and normalized == value
        and all(char.islower() or char.isdigit() or char in "-_" for char in value)
    )


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False
