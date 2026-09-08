from dataclasses import dataclass

from proxyscope.application.journal import LoggedExchange


@dataclass
class RequestFilter:
    host: str | None = None
    method: str | None = None
    status_code: int | None = None
    text: str | None = None

    def is_active(self) -> bool:
        return any((self.host, self.method, self.status_code is not None, self.text))

    def summary(self) -> str:
        parts: list[str] = []
        if self.host:
            parts.append(f"host={self.host}")
        if self.method:
            parts.append(f"method={self.method}")
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.text:
            parts.append(f"text={self.text}")
        return " ".join(parts) if parts else "off"

    def matches(self, entry: LoggedExchange) -> bool:
        if self.host is not None and (entry.target_host or "").lower() != self.host:
            return False
        if self.method is not None and entry.request.method.upper() != self.method:
            return False
        if self.status_code is not None and (entry.response is None or entry.response.status_code != self.status_code):
            return False
        return self.text is None or self.text in _entry_search_text(entry)

    def select(self, entries: list[LoggedExchange]) -> list[LoggedExchange]:
        if not self.is_active():
            return entries
        return [entry for entry in entries if self.matches(entry)]

    def clear(self) -> None:
        self.host = None
        self.method = None
        self.status_code = None
        self.text = None


def _entry_search_text(entry: LoggedExchange) -> str:
    parts = [
        entry.request.method,
        entry.request.path,
        entry.target_host or "",
        entry.client_ip,
        entry.request.body_preview,
    ]
    parts.extend(f"{name}: {value}" for name, value in entry.request.headers)
    if entry.response is not None:
        parts.extend((str(entry.response.status_code), entry.response.reason, entry.response.body_preview))
        parts.extend(f"{name}: {value}" for name, value in entry.response.headers)
    return "\n".join(parts).lower()
