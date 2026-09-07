import logging
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from threading import RLock

from proxyscope.application.configuration.models import RuntimeSettings, normalize_whitelist_entry


class RuntimeSettingsState:
    def __init__(
        self,
        *,
        settings: RuntimeSettings | None = None,
        log_level: int = logging.INFO,
        log_whitelist: Iterable[str] = (),
        cache_invalidation_enabled: bool = True,
        mitm_enabled: bool = True,
        mitm_certs_dir: str | Path = "certs",
    ) -> None:
        self._lock = RLock()
        source = settings or RuntimeSettings.create(
            log_level=log_level,
            log_whitelist=(normalize_whitelist_entry(entry) for entry in log_whitelist),
            cache_invalidation_enabled=cache_invalidation_enabled,
            mitm_enabled=mitm_enabled,
            mitm_certs_dir=mitm_certs_dir,
        )
        self._settings = _normalize_settings(source)

    @property
    def snapshot(self) -> RuntimeSettings:
        with self._lock:
            return self._settings

    @property
    def log_level(self) -> int:
        return self.snapshot.log_level

    def log_level_name(self) -> str:
        return logging.getLevelName(self.log_level)

    def set_log_level(self, value: str | int) -> int:
        if isinstance(value, int):
            new_level = value
        else:
            normalized = value.strip().upper()
            if not normalized:
                raise ValueError("Log level must not be empty.")
            new_level = getattr(logging, normalized, None)
            if not isinstance(new_level, int):
                raise ValueError(f"Unsupported log level: {value}")
        self._replace(log_level=new_level)
        return new_level

    def whitelist_entries(self) -> tuple[str, ...]:
        return tuple(sorted(self.snapshot.log_whitelist))

    def add_whitelist_entry(self, value: str) -> str:
        normalized_host = normalize_whitelist_entry(value)
        with self._lock:
            entries = tuple(sorted(set(self._settings.log_whitelist) | {normalized_host}))
            self._replace(log_whitelist=entries)
        return normalized_host

    def remove_whitelist_entry(self, value: str) -> bool:
        normalized_host = normalize_whitelist_entry(value)
        with self._lock:
            entries = set(self._settings.log_whitelist)
            if normalized_host not in entries:
                return False
            entries.remove(normalized_host)
            self._replace(log_whitelist=tuple(sorted(entries)))
        return True

    def clear_whitelist(self) -> None:
        self._replace(log_whitelist=())

    def should_log_for_host(self, host: str | None) -> bool:
        whitelist = self.snapshot.log_whitelist
        if not whitelist:
            return True
        if host is None:
            return False
        return normalize_whitelist_entry(host) in whitelist

    @property
    def cache_invalidation_enabled(self) -> bool:
        return self.snapshot.cache_invalidation_enabled

    def set_cache_invalidation_enabled(self, enabled: bool) -> bool:
        self._replace(cache_invalidation_enabled=enabled)
        return enabled

    def toggle_cache_invalidation(self) -> bool:
        with self._lock:
            return self.set_cache_invalidation_enabled(not self._settings.cache_invalidation_enabled)

    @property
    def mitm_enabled(self) -> bool:
        return self.snapshot.mitm_enabled

    def set_mitm_enabled(self, enabled: bool) -> bool:
        self._replace(mitm_enabled=enabled)
        return enabled

    @property
    def mitm_certs_dir(self) -> Path:
        return self.snapshot.mitm_certs_dir

    def set_mitm_certs_dir(self, value: str | Path) -> Path:
        normalized = Path(value)
        self._replace(mitm_certs_dir=normalized)
        return normalized

    def apply(self, settings: RuntimeSettings) -> None:
        with self._lock:
            self._settings = _normalize_settings(settings)

    def _replace(self, **changes: object) -> None:
        with self._lock:
            self._settings = replace(self._settings, **changes)


def _normalize_settings(settings: RuntimeSettings) -> RuntimeSettings:
    return RuntimeSettings.create(
        log_level=settings.log_level,
        log_whitelist=(normalize_whitelist_entry(entry) for entry in settings.log_whitelist),
        cache_invalidation_enabled=settings.cache_invalidation_enabled,
        mitm_enabled=settings.mitm_enabled,
        mitm_certs_dir=settings.mitm_certs_dir,
    )
