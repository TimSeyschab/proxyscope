from collections import Counter
from dataclasses import dataclass
from threading import Lock

from proxyscope.application.journal import LoggedExchange, RequestJournal


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

    def clear(self) -> None:
        self.host = None
        self.method = None
        self.status_code = None
        self.text = None


@dataclass(frozen=True)
class RequestWindow:
    entries: list[LoggedExchange]
    offset: int
    total_count: int
    all_count: int
    selected_entry: LoggedExchange | None


class RequestApplicationService:
    def __init__(self, request_journal: RequestJournal) -> None:
        self._request_journal = request_journal
        self._filter = RequestFilter()
        self._sites: Counter[str] = Counter()
        self._lock = Lock()

    @property
    def filter_summary(self) -> str:
        return self._filter.summary()

    def list_entries(self) -> list[LoggedExchange]:
        entries = self.list_all_entries()
        if self._filter.is_active():
            entries = [entry for entry in entries if self._filter.matches(entry)]
        return entries

    def list_window(self, *, cursor: int, limit: int) -> RequestWindow:
        all_entries = self.list_all_entries()
        entries = all_entries
        if self._filter.is_active():
            entries = [entry for entry in entries if self._filter.matches(entry)]

        total_count = len(entries)
        if limit <= 0:
            selected_index = min(max(cursor, 0), total_count - 1) if total_count else None
            return RequestWindow(
                entries=[],
                offset=0,
                total_count=total_count,
                all_count=len(all_entries),
                selected_entry=None if selected_index is None else entries[selected_index],
            )

        offset = _window_offset(cursor=cursor, total_count=total_count, limit=limit)
        selected_index = min(max(cursor, 0), total_count - 1) if total_count else None
        return RequestWindow(
            entries=entries[offset : offset + limit],
            offset=offset,
            total_count=total_count,
            all_count=len(all_entries),
            selected_entry=None if selected_index is None else entries[selected_index],
        )

    def list_all_entries(self) -> list[LoggedExchange]:
        entries = list(self._request_journal.list_entries())
        entries.reverse()
        return entries

    def clear(self) -> str:
        self._request_journal.clear()
        return "Request list cleared."

    def apply_filter(self, arguments: list[str]) -> str:
        if not arguments or arguments[0].lower() == "show":
            return f"Request filter: {self._filter.summary()}"
        action = arguments[0].lower()
        value = " ".join(arguments[1:]).strip()
        if action == "clear":
            self._filter.clear()
            return "Request filter cleared."
        if action == "host":
            if not value:
                return "Usage: filter host <hostname>|clear"
            self._filter.host = None if value.lower() == "clear" else value.lower()
        elif action == "method":
            if not value:
                return "Usage: filter method <HTTP method>|clear"
            self._filter.method = None if value.lower() == "clear" else value.upper()
        elif action == "status":
            if not value:
                return "Usage: filter status <HTTP status>|clear"
            if value.lower() == "clear":
                self._filter.status_code = None
            else:
                try:
                    self._filter.status_code = int(value)
                except ValueError:
                    return "Status filter must be an integer."
        elif action == "text":
            if not value:
                return "Usage: filter text <search text>|clear"
            self._filter.text = None if value.lower() == "clear" else value.lower()
        else:
            return "Usage: filter [show|clear|host|method|status|text] ..."
        return f"Request filter: {self._filter.summary()}"

    def find(self, arguments: list[str]) -> str:
        query = " ".join(arguments).strip()
        if not query:
            return "Usage: find <search text>|clear"
        self._filter.text = None if query.lower() == "clear" else query.lower()
        return f"Request filter: {self._filter.summary()}"

    def record_site_visit(self, host: str) -> None:
        with self._lock:
            self._sites[host] += 1

    def site_counter(self) -> Counter[str]:
        with self._lock:
            return self._sites.copy()

    def site_names(self) -> list[str]:
        return [host for host, _count in self.site_counter().most_common()]

    def top_sites_summary(self, *, limit: int = 5) -> str:
        top_sites = self.site_counter().most_common(limit)
        if not top_sites:
            return "No sites recorded yet."
        summary = ", ".join(f"{host} ({count})" for host, count in top_sites)
        return f"Top sites: {summary}"


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


def _window_offset(*, cursor: int, total_count: int, limit: int) -> int:
    if total_count <= 0 or limit <= 0:
        return 0
    clamped_cursor = min(max(cursor, 0), total_count - 1)
    if total_count <= limit:
        return 0
    return min(max(clamped_cursor - limit // 2, 0), total_count - limit)
