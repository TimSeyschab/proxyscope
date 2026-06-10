import json
import logging
from collections.abc import Iterable
from pathlib import Path
from threading import RLock

from proxyscope.app.config.matching import (
    first_rule_method,
    normalize_http_method,
    normalize_modification_url,
    normalize_whitelist_entry,
    policy_description,
    policy_rule_matches_request,
    policy_sort_key,
    request_url_candidates,
    rule_matches_url,
    rule_method_display,
    rule_url_display,
)
from proxyscope.app.config.models import PolicyRule, RequestMatchRule, StaticResponseTemplate
from proxyscope.app.config.serialization import (
    parse_policy_rule as parse_policy_rule_payload,
)
from proxyscope.app.config.serialization import (
    serialize_policy_rule as serialize_policy_rule_payload,
)


class RuntimeConfig:
    """
    Runtime configuration shared by logging, policy matching, and UI.
    """

    def __init__(
        self,
        *,
        log_level: int = logging.INFO,
        log_whitelist: Iterable[str] | None = None,
        cache_invalidation_enabled: bool = True,
        mitm_enabled: bool = True,
        mitm_certs_dir: str | Path = "certs",
        config_path: str | Path | None = None,
        policy_rules: Iterable[PolicyRule] | None = None,
    ) -> None:
        self._lock = RLock()
        self._log_level = log_level
        self._log_whitelist: set[str] = set()
        self._cache_invalidation_enabled = cache_invalidation_enabled
        self._mitm_enabled = mitm_enabled
        self._mitm_certs_dir = Path(mitm_certs_dir)
        self._config_path = Path(config_path) if config_path is not None else None
        self._policy_rules: list[PolicyRule] = list(policy_rules or [])

        if log_whitelist is not None:
            for entry in log_whitelist:
                self._log_whitelist.add(normalize_whitelist_entry(entry))

    @property
    def config_path(self) -> Path | None:
        with self._lock:
            return self._config_path

    @property
    def log_level(self) -> int:
        with self._lock:
            return self._log_level

    def log_level_name(self) -> str:
        with self._lock:
            return logging.getLevelName(self._log_level)

    def set_log_level(self, value: str | int) -> int:
        with self._lock:
            if isinstance(value, int):
                new_level = value
            else:
                normalized = value.strip().upper()
                if not normalized:
                    raise ValueError("Log level must not be empty.")
                new_level = getattr(logging, normalized, None)
                if not isinstance(new_level, int):
                    raise ValueError(f"Unsupported log level: {value}")
            self._log_level = new_level
        self._persist_if_configured()
        return new_level

    def whitelist_entries(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._log_whitelist))

    def add_whitelist_entry(self, value: str) -> str:
        normalized_host = normalize_whitelist_entry(value)
        with self._lock:
            self._log_whitelist.add(normalized_host)
        self._persist_if_configured()
        return normalized_host

    def remove_whitelist_entry(self, value: str) -> bool:
        normalized_host = normalize_whitelist_entry(value)
        removed = False
        with self._lock:
            if normalized_host in self._log_whitelist:
                self._log_whitelist.remove(normalized_host)
                removed = True
        if removed:
            self._persist_if_configured()
        return removed

    def clear_whitelist(self) -> None:
        with self._lock:
            self._log_whitelist.clear()
        self._persist_if_configured()

    def should_log_for_host(self, host: str | None) -> bool:
        with self._lock:
            if not self._log_whitelist:
                return True
            if host is None:
                return False
            normalized_host = normalize_whitelist_entry(host)
            return normalized_host in self._log_whitelist

    @property
    def cache_invalidation_enabled(self) -> bool:
        with self._lock:
            return self._cache_invalidation_enabled

    @property
    def mitm_enabled(self) -> bool:
        with self._lock:
            return self._mitm_enabled

    @property
    def mitm_certs_dir(self) -> Path:
        with self._lock:
            return self._mitm_certs_dir

    def set_cache_invalidation_enabled(self, enabled: bool) -> bool:
        with self._lock:
            self._cache_invalidation_enabled = enabled
        self._persist_if_configured()
        return enabled

    def toggle_cache_invalidation(self) -> bool:
        with self._lock:
            self._cache_invalidation_enabled = not self._cache_invalidation_enabled
            enabled = self._cache_invalidation_enabled
        self._persist_if_configured()
        return enabled

    def set_mitm_enabled(self, enabled: bool) -> bool:
        with self._lock:
            self._mitm_enabled = enabled
        self._persist_if_configured()
        return enabled

    def set_mitm_certs_dir(self, value: str | Path) -> Path:
        normalized = Path(value)
        with self._lock:
            self._mitm_certs_dir = normalized
        self._persist_if_configured()
        return normalized

    def policy_rules(self) -> tuple[PolicyRule, ...]:
        with self._lock:
            return tuple(self._policy_rules)

    def sorted_policy_rules(self) -> tuple[PolicyRule, ...]:
        with self._lock:
            ordered = sorted(self._policy_rules, key=policy_sort_key, reverse=True)
            return tuple(ordered)

    def set_policy_rules(self, rules: Iterable[PolicyRule]) -> None:
        with self._lock:
            self._policy_rules = list(rules)
        self._persist_if_configured()

    def add_policy_rule(self, rule: PolicyRule) -> None:
        with self._lock:
            self._policy_rules.append(rule)
        self._persist_if_configured()

    def clear_policy_rules(self) -> None:
        with self._lock:
            self._policy_rules.clear()
        self._persist_if_configured()

    def policy_descriptions(self) -> tuple[str, ...]:
        return tuple(policy_description(rule) for rule in self.sorted_policy_rules())

    def remove_policy_rule(self, name: str) -> bool:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Policy name must not be empty.")
        removed = False
        with self._lock:
            kept: list[PolicyRule] = []
            for rule in self._policy_rules:
                if rule.name == normalized:
                    removed = True
                    continue
                kept.append(rule)
            self._policy_rules = kept
        if removed:
            self._persist_if_configured()
        return removed

    def get_policy_rule(self, name: str) -> PolicyRule | None:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Policy name must not be empty.")
        with self._lock:
            for rule in self._policy_rules:
                if rule.name == normalized:
                    return rule
        return None

    def replace_policy_rule(self, name: str, replacement: PolicyRule) -> bool:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Policy name must not be empty.")
        replaced = False
        with self._lock:
            updated: list[PolicyRule] = []
            for rule in self._policy_rules:
                if not replaced and rule.name == normalized:
                    updated.append(replacement)
                    replaced = True
                    continue
                updated.append(rule)
            self._policy_rules = updated
        if replaced:
            self._persist_if_configured()
        return replaced

    def set_policy_rule_enabled(self, name: str, *, enabled: bool) -> bool:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Policy name must not be empty.")
        changed = False
        with self._lock:
            updated: list[PolicyRule] = []
            for rule in self._policy_rules:
                if rule.name != normalized:
                    updated.append(rule)
                    continue
                updated.append(
                    PolicyRule(
                        name=rule.name,
                        enabled=enabled,
                        priority=rule.priority,
                        action=rule.action,
                        match=rule.match,
                        static_response=rule.static_response,
                    )
                )
                changed = True
            self._policy_rules = updated
        if changed:
            self._persist_if_configured()
        return changed

    def add_static_response_rule(
        self,
        *,
        url: str,
        status_code: int = 200,
        reason: str = "OK",
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        method: str | None = None,
        url_prefix: bool = False,
        name: str | None = None,
        priority: int = 0,
    ) -> str:
        normalized_url = normalize_modification_url(url)
        normalized_method = normalize_http_method(method) if method is not None else None
        rule_name = name or f"static-response-{len(self._policy_rules) + 1}"
        match = RequestMatchRule(
            methods=(normalized_method,) if normalized_method is not None else None,
            url_prefix=normalized_url if url_prefix else None,
            url_exact=None if url_prefix else normalized_url,
        )
        self.add_policy_rule(
            PolicyRule(
                name=rule_name,
                enabled=True,
                priority=priority,
                action="static_response",
                match=match,
                static_response=StaticResponseTemplate(
                    status_code=status_code,
                    reason=reason,
                    headers=dict(headers or {}),
                    body=body,
                ),
            )
        )
        return rule_name

    def modification_whitelist_entries(self) -> tuple[str, ...]:
        with self._lock:
            entries = [rule for rule in self._policy_rules if rule.action == "open_editor" and rule.enabled]
            return tuple(f"{rule_method_display(rule)} {rule_url_display(rule)}" for rule in entries)

    def open_editor_policy_entries(self) -> tuple[str, ...]:
        return self.modification_whitelist_entries()

    def add_open_editor_policy(
        self,
        value: str,
        *,
        method: str = "GET",
        url_prefix: bool = False,
        priority: int = 0,
    ) -> str:
        return self.add_modification_whitelist_entry(value, method=method, url_prefix=url_prefix, priority=priority)

    def remove_open_editor_policy(self, value: str, *, method: str | None = None) -> bool:
        return self.remove_modification_whitelist_entry(value, method=method)

    def clear_open_editor_policies(self) -> None:
        self.clear_modification_whitelist()

    def add_modification_whitelist_entry(
        self,
        value: str,
        *,
        method: str = "GET",
        url_prefix: bool = False,
        priority: int = 0,
    ) -> str:
        normalized_url = normalize_modification_url(value)
        normalized_method = normalize_http_method(method)
        name = f"open-editor-{len(self._policy_rules) + 1}"
        self.add_policy_rule(
            PolicyRule(
                name=name,
                enabled=True,
                priority=priority,
                action="open_editor",
                match=RequestMatchRule(
                    methods=(normalized_method,),
                    url_exact=None if url_prefix else normalized_url,
                    url_prefix=normalized_url if url_prefix else None,
                ),
            )
        )
        return f"{normalized_method} {normalized_url}"

    def set_policy_rule_priority(self, name: str, *, priority: int) -> bool:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Policy name must not be empty.")
        changed = False
        with self._lock:
            updated: list[PolicyRule] = []
            for rule in self._policy_rules:
                if rule.name != normalized:
                    updated.append(rule)
                    continue
                updated.append(
                    PolicyRule(
                        name=rule.name,
                        enabled=rule.enabled,
                        priority=priority,
                        action=rule.action,
                        match=rule.match,
                        static_response=rule.static_response,
                    )
                )
                changed = True
            self._policy_rules = updated
        if changed:
            self._persist_if_configured()
        return changed

    def remove_modification_whitelist_entry(self, value: str, *, method: str | None = None) -> bool:
        normalized_url = normalize_modification_url(value)
        normalized_method = normalize_http_method(method) if method is not None else None
        removed = False
        with self._lock:
            kept: list[PolicyRule] = []
            for rule in self._policy_rules:
                if rule.action != "open_editor":
                    kept.append(rule)
                    continue
                if not rule_matches_url(rule, normalized_url):
                    kept.append(rule)
                    continue
                rule_method = first_rule_method(rule)
                if normalized_method is not None and rule_method != normalized_method:
                    kept.append(rule)
                    continue
                removed = True
            self._policy_rules = kept
        if removed:
            self._persist_if_configured()
        return removed

    def clear_modification_whitelist(self) -> None:
        with self._lock:
            self._policy_rules = [rule for rule in self._policy_rules if rule.action != "open_editor"]
        self._persist_if_configured()

    def should_modify_response_for_request(self, *, method: str, url: str) -> bool:
        normalized_method = normalize_http_method(method)
        candidates = request_url_candidates(url)
        with self._lock:
            matching_rules = sorted(self._policy_rules, key=policy_sort_key, reverse=True)
            for rule in matching_rules:
                if not rule.enabled or rule.action != "open_editor":
                    continue
                if policy_rule_matches_request(rule=rule, method=normalized_method, url_candidates=candidates):
                    return True
            return False

    def get_static_response_template_for_request(
        self,
        *,
        method: str,
        url: str,
    ) -> StaticResponseTemplate | None:
        normalized_method = normalize_http_method(method)
        candidates = request_url_candidates(url)
        with self._lock:
            matching_rules = sorted(self._policy_rules, key=policy_sort_key, reverse=True)
            for rule in matching_rules:
                if not rule.enabled or rule.action != "static_response":
                    continue
                if policy_rule_matches_request(rule=rule, method=normalized_method, url_candidates=candidates):
                    return rule.static_response
            return None

    def attach_config_path(self, path: str | Path) -> None:
        with self._lock:
            self._config_path = Path(path)

    def save_to_path(self, path: str | Path) -> Path:
        resolved = Path(path)
        with self._lock:
            self._config_path = resolved
        self.save()
        return resolved

    def reload_from_attached_file(self) -> bool:
        with self._lock:
            path = self._config_path
        if path is None:
            return False
        reloaded = RuntimeConfig.load_from_file(path)
        with self._lock:
            self._log_level = reloaded.log_level
            self._log_whitelist = set(reloaded.whitelist_entries())
            self._cache_invalidation_enabled = reloaded.cache_invalidation_enabled
            self._mitm_enabled = reloaded.mitm_enabled
            self._mitm_certs_dir = reloaded.mitm_certs_dir
            self._policy_rules = list(reloaded.policy_rules())
        return True

    def save(self) -> None:
        with self._lock:
            path = self._config_path
            payload = self._to_dict_locked()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    def _persist_if_configured(self) -> None:
        with self._lock:
            has_path = self._config_path is not None
        if has_path:
            self.save()

    def _to_dict_locked(self) -> dict:
        return {
            "log_level": logging.getLevelName(self._log_level),
            "log_whitelist": sorted(self._log_whitelist),
            "cache_invalidation_enabled": self._cache_invalidation_enabled,
            "mitm_enabled": self._mitm_enabled,
            "mitm_certs_dir": str(self._mitm_certs_dir),
            "policies": [serialize_policy_rule_payload(rule) for rule in self._policy_rules],
        }

    @classmethod
    def load_from_file(cls, path: str | Path) -> "RuntimeConfig":
        resolved_path = Path(path)
        if not resolved_path.exists():
            return cls(config_path=resolved_path)

        raw = json.loads(resolved_path.read_text(encoding="utf-8"))
        level_raw = str(raw.get("log_level", "INFO")).strip().upper()
        level_value = getattr(logging, level_raw, logging.INFO)
        whitelist_raw = raw.get("log_whitelist", [])
        cache_enabled = bool(raw.get("cache_invalidation_enabled", False))
        mitm_enabled = bool(raw.get("mitm_enabled", True))
        mitm_certs_dir = raw.get("mitm_certs_dir", "certs")

        rules: list[PolicyRule] = []
        for item in raw.get("policies", []):
            parsed = parse_policy_rule_payload(item)
            if parsed is not None:
                rules.append(parsed)

        return cls(
            log_level=level_value,
            log_whitelist=whitelist_raw,
            cache_invalidation_enabled=cache_enabled,
            mitm_enabled=mitm_enabled,
            mitm_certs_dir=mitm_certs_dir,
            config_path=resolved_path,
            policy_rules=rules,
        )


_runtime_config = RuntimeConfig()
_runtime_config_lock = RLock()


def set_runtime_config(config: RuntimeConfig) -> None:
    global _runtime_config
    with _runtime_config_lock:
        _runtime_config = config


def get_runtime_config() -> RuntimeConfig:
    with _runtime_config_lock:
        return _runtime_config


def should_log_for_host(host: str | None) -> bool:
    return get_runtime_config().should_log_for_host(host)


def is_cache_invalidation_enabled() -> bool:
    return get_runtime_config().cache_invalidation_enabled


def should_modify_response_for_request(*, method: str, url: str) -> bool:
    return get_runtime_config().should_modify_response_for_request(method=method, url=url)


def get_static_response_template_for_request(*, method: str, url: str) -> StaticResponseTemplate | None:
    return get_runtime_config().get_static_response_template_for_request(method=method, url=url)


def serialize_policy_rule(rule: PolicyRule) -> dict:
    return serialize_policy_rule_payload(rule)


def parse_policy_rule(data: object) -> PolicyRule | None:
    return parse_policy_rule_payload(data)
