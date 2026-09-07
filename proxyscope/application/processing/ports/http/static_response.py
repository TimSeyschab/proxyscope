from typing import Protocol


class StaticResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def reason(self) -> str: ...

    @property
    def headers(self) -> dict[str, str]: ...

    @property
    def body(self) -> bytes: ...
