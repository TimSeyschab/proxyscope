import json

from proxyscope.app.runtime.exporting import export_entries, load_entries_from_json
from proxyscope.app.runtime.journal import RequestJournal


class SessionApplicationService:
    def __init__(self, request_journal: RequestJournal) -> None:
        self._request_journal = request_journal

    def export(self, arguments: list[str]) -> str:
        if len(arguments) < 2:
            return "Usage: export <json|har> <path>"
        format_name = arguments[0].lower()
        path = " ".join(arguments[1:]).strip()
        if not path:
            return "Usage: export <json|har> <path>"
        try:
            destination = export_entries(
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
                destination = export_entries(
                    list(self._request_journal.list_entries()),
                    format_name="json",
                    destination=path,
                )
            except OSError as exc:
                return f"Session save failed ({exc})."
            return f"Saved session snapshot to {destination}"
        if action == "load":
            try:
                entries = load_entries_from_json(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return f"Session load failed ({exc})."
            self._request_journal.replace_entries(entries)
            return f"Loaded session snapshot from {path}"
        return "Usage: session <save|load> <path>"
