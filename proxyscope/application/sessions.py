import json
from pathlib import Path
from typing import Callable

from proxyscope.application.journal import LoggedExchange, RequestJournal

ExportEntries = Callable[..., Path]
LoadEntries = Callable[[str], list[LoggedExchange]]


class SessionApplicationService:
    def __init__(
        self,
        request_journal: RequestJournal,
        *,
        export_entries: ExportEntries,
        load_entries: LoadEntries,
    ) -> None:
        self._request_journal = request_journal
        self._export_entries = export_entries
        self._load_entries = load_entries

    def export(self, arguments: list[str]) -> str:
        if len(arguments) < 2:
            return "Usage: export <json|har> <path>"
        format_name = arguments[0].lower()
        path = " ".join(arguments[1:]).strip()
        if not path:
            return "Usage: export <json|har> <path>"
        try:
            destination = self._export_entries(
                list(self._request_journal.list_entries()),
                format_name=format_name,
                destination=path,
            )
        except ValueError as exc:
            return str(exc)
        except OSError as exc:
            return f"Export failed ({exc})."
        return f"Exported {format_name} snapshot to {destination}"

    def session(self, arguments: list[str]) -> str:
        if len(arguments) < 2:
            return "Usage: session <save|load> <path>"
        action = arguments[0].lower()
        path = " ".join(arguments[1:]).strip()
        if not path:
            return "Usage: session <save|load> <path>"
        if action == "save":
            try:
                destination = self._export_entries(
                    list(self._request_journal.list_entries()),
                    format_name="json",
                    destination=path,
                )
            except OSError as exc:
                return f"Session save failed ({exc})."
            return f"Saved session snapshot to {destination}"
        if action == "load":
            try:
                entries = self._load_entries(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return f"Session load failed ({exc})."
            self._request_journal.replace_entries(entries)
            return f"Loaded session snapshot from {path}"
        return "Usage: session <save|load> <path>"
