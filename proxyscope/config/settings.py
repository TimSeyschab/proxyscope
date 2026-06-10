import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from proxyscope.policies.models import PolicyRule


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
class ConfigDocument:
    settings: RuntimeSettings
    policies: tuple[PolicyRule, ...] = ()
