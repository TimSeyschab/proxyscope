CURRENT_SCHEMA_VERSION = 1


class ConfigMigrationError(ValueError):
    pass


def migrate_config_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ConfigMigrationError("Config root must be a JSON object.")

    version = payload.get("schema_version")
    if version is None:
        return _migrate_legacy_payload(payload)
    if not isinstance(version, int):
        raise ConfigMigrationError("schema_version must be an integer.")
    if version != CURRENT_SCHEMA_VERSION:
        raise ConfigMigrationError(f"Unsupported schema_version {version}; expected {CURRENT_SCHEMA_VERSION}.")
    return dict(payload)


def _migrate_legacy_payload(payload: dict) -> dict:
    known = {
        "log_level",
        "log_whitelist",
        "cache_invalidation_enabled",
        "mitm_enabled",
        "mitm_certs_dir",
        "policies",
        "policy_shortcuts",
    }
    unknown = sorted(set(payload) - known)
    if unknown:
        raise ConfigMigrationError(f"Unknown legacy config field(s): {', '.join(unknown)}.")
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "settings": {
            "log_level": payload.get("log_level", "INFO"),
            "log_whitelist": payload.get("log_whitelist", []),
            "cache_invalidation_enabled": payload.get("cache_invalidation_enabled", False),
            "mitm_enabled": payload.get("mitm_enabled", True),
            "mitm_certs_dir": payload.get("mitm_certs_dir", "certs"),
        },
        "policies": payload.get("policies", []),
        "policy_shortcuts": payload.get("policy_shortcuts", []),
    }
