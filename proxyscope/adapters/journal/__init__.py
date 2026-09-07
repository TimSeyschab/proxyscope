from proxyscope.application.actions import entry_to_url
from proxyscope.application.journal import LoggedExchange, RequestJournal
from proxyscope.contracts.ports import CapturedExchange, CapturedResponse


class JournalAdapter:
    def __init__(self, journal: RequestJournal) -> None:
        self._journal = journal

    def get_entry(self, request_id: int) -> CapturedExchange | None:
        entry = self._journal.get_entry(request_id)
        return None if entry is None else _capture(entry)

    def list_entries(self) -> tuple[CapturedExchange, ...]:
        return tuple(_capture(entry) for entry in self._journal.list_entries())


def _capture(entry: LoggedExchange) -> CapturedExchange:
    response = entry.response
    return CapturedExchange(
        request_id=entry.request_id,
        method=entry.request.method,
        url=entry_to_url(entry),
        response=None
        if response is None
        else CapturedResponse(
            status_code=response.status_code,
            reason=response.reason,
            headers=response.headers,
            body=response.body,
            body_size=response.body_size,
        ),
    )


__all__ = ["JournalAdapter"]
