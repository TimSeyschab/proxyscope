from typing import Protocol, runtime_checkable


@runtime_checkable
class CachePolicy(Protocol):
    @property
    def cache_invalidation_enabled(self) -> bool: ...
