from dataclasses import replace

from proxyscope.processing.models import ExchangeRequest
from proxyscope.processing.ports import CachePolicy


class CacheInvalidationMiddleware:
    def __init__(self, cache_policy: CachePolicy) -> None:
        self._cache_policy = cache_policy

    def process_request(self, request: ExchangeRequest) -> ExchangeRequest:
        return replace(request, headers=self.rewrite_headers(request.headers))

    def rewrite_headers(self, headers: dict[str, str]) -> dict[str, str]:
        if not self._cache_policy.cache_invalidation_enabled:
            return dict(headers)
        return rewrite_cache_invalidation_headers(headers)


def rewrite_cache_invalidation_headers(headers: dict[str, str]) -> dict[str, str]:
    rewritten: dict[str, str] = {}
    blocked = {
        "if-none-match",
        "if-modified-since",
        "cache-control",
        "pragma",
        "expires",
        "accept-encoding",
    }
    for key, value in headers.items():
        if key.lower() not in blocked:
            rewritten[key] = value

    rewritten["Cache-Control"] = "no-cache, no-store, max-age=0, must-revalidate"
    rewritten["Pragma"] = "no-cache"
    rewritten["Expires"] = "0"
    rewritten["Accept-Encoding"] = "identity"
    return rewritten
