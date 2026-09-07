from dataclasses import dataclass

from proxyscope.application.actions import ReplayRequest, ResponseEditor
from proxyscope.application.sessions import ExportEntries, LoadEntries


@dataclass(frozen=True)
class RuntimeApplicationAdapters:
    replay_request: ReplayRequest
    response_editor: ResponseEditor
    export_entries: ExportEntries
    load_entries: LoadEntries
