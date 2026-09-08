from collections import Counter
from threading import Lock

from proxyscope.application.journal import LoggedExchange, RequestJournal

from .filters import RequestFilter
from .window import RequestWindow

FILTER_ARGUMENTS = {
    "host": "hostname",
    "method": "HTTP method",
    "status": "HTTP status",
    "text": "search text",
}


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
        return self._filter.select(self.list_all_entries())

    def list_window(self, *, cursor: int, limit: int) -> RequestWindow:
        all_entries = self.list_all_entries()
        return RequestWindow.from_entries(
            self._filter.select(all_entries), cursor=cursor, limit=limit, all_count=len(all_entries)
        )

    def list_all_entries(self) -> list[LoggedExchange]:
        return list(reversed(self._request_journal.list_entries()))

    def clear(self) -> str:
        self._request_journal.clear()
        return "Request list cleared."

    def apply_filter(self, arguments: list[str]) -> str:
        if not arguments or arguments[0].lower() == "show":
            return f"Request filter: {self.filter_summary}"
        action = arguments[0].lower()
        if action == "clear":
            self._filter.clear()
            return "Request filter cleared."
        if action not in FILTER_ARGUMENTS:
            return "Usage: filter [show|clear|host|method|status|text] ..."
        value = " ".join(arguments[1:]).strip()
        if not value:
            return f"Usage: filter {action} <{FILTER_ARGUMENTS[action]}>|clear"
        normalized = None if value.lower() == "clear" else value
        if action == "host":
            self._filter.host = None if normalized is None else normalized.lower()
        elif action == "method":
            self._filter.method = None if normalized is None else normalized.upper()
        elif action == "status":
            try:
                self._filter.status_code = None if normalized is None else int(normalized)
            except ValueError:
                return "Status filter must be an integer."
        else:
            self._filter.text = None if normalized is None else normalized.lower()
        return f"Request filter: {self.filter_summary}"

    def find(self, arguments: list[str]) -> str:
        query = " ".join(arguments).strip()
        if not query:
            return "Usage: find <search text>|clear"
        return self.apply_filter(["text", query])

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
