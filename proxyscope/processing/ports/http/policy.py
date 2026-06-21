from typing import Protocol, runtime_checkable

from proxyscope.processing.ports.http.static_response import StaticResponse


@runtime_checkable
class PolicyEvaluator(Protocol):
    def should_modify_response_for_request(self, *, method: str, url: str) -> bool: ...

    def get_static_response_template_for_request(self, *, method: str, url: str) -> StaticResponse | None: ...
