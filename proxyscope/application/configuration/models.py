import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from proxyscope.application.configuration.component_settings import ComponentSettings


def normalize_whitelist_entry(value: str) -> str:
    raw_value = value.strip()
    if not raw_value:
        raise ValueError("Whitelist entry must not be empty.")
    parsed = urlsplit(raw_value if "://" in raw_value else f"http://{raw_value}")
    if not parsed.hostname:
        raise ValueError(f"Invalid whitelist entry: {value}")
    return parsed.hostname.lower()


@dataclass(frozen=True)
class RuntimeSettings:
    log_level: int = logging.INFO
    log_whitelist: tuple[str, ...] = ()
    cache_invalidation_enabled: bool = True
    mitm_enabled: bool = True
    mitm_certs_dir: Path = Path("certs")

    @classmethod
    def create(
        cls,
        *,
        log_level: int = logging.INFO,
        log_whitelist: Iterable[str] = (),
        cache_invalidation_enabled: bool = True,
        mitm_enabled: bool = True,
        mitm_certs_dir: str | Path = "certs",
    ) -> "RuntimeSettings":
        return cls(
            log_level=log_level,
            log_whitelist=tuple(log_whitelist),
            cache_invalidation_enabled=cache_invalidation_enabled,
            mitm_enabled=mitm_enabled,
            mitm_certs_dir=Path(mitm_certs_dir),
        )


@dataclass(frozen=True)
class EventStoreSettings:
    enabled: bool = False
    path: Path = Path(".proxyscope/events.sqlite3")
    max_body_bytes: int = 4096
    max_events: int | None = None
    max_age_days: int | None = None
    max_storage_bytes: int | None = None
    queue_size: int = 128

    @classmethod
    def create(
        cls,
        *,
        enabled: bool = False,
        path: str | Path = ".proxyscope/events.sqlite3",
        max_body_bytes: int = 4096,
        max_events: int | None = None,
        max_age_days: int | None = None,
        max_storage_bytes: int | None = None,
        queue_size: int = 128,
    ) -> "EventStoreSettings":
        return cls(
            enabled=enabled,
            path=Path(path),
            max_body_bytes=max_body_bytes,
            max_events=max_events,
            max_age_days=max_age_days,
            max_storage_bytes=max_storage_bytes,
            queue_size=queue_size,
        )


@dataclass(frozen=True)
class ConfigDocument:
    settings: RuntimeSettings
    event_store: EventStoreSettings = EventStoreSettings()
    traffic_rules: tuple[dict[str, object], ...] = ()
    components: ComponentSettings = ComponentSettings()
