import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from proxyscope.application.journal import RequestJournal
from proxyscope.application.sessions import SessionApplicationService
from tests.support.exchanges import recorded_exchange


@pytest.fixture
def session_context():
    journal = RequestJournal()
    journal.replace_entries([recorded_exchange()])
    export = Mock(return_value=Path("saved session.json"))
    load = Mock(return_value=[recorded_exchange(host="loaded.test")])
    return SessionApplicationService(journal, export_entries=export, load_entries=load), journal, export, load


@pytest.mark.parametrize("method", ["export", "session"])
@pytest.mark.parametrize("arguments", [[], ["save"], ["save", "  "], ["save", "", " "]])
def test_missing_path_does_not_invoke_adapters(session_context, method, arguments):
    service, _, export, load = session_context
    assert getattr(service, method)(arguments).startswith("Usage:")
    export.assert_not_called()
    load.assert_not_called()


def test_export_normalizes_format_and_preserves_path_spaces(session_context):
    service, journal, export, _ = session_context
    assert service.export(["HAR", "saved", "session.json"]) == "Exported har snapshot to saved session.json"
    export.assert_called_once_with(list(journal.list_entries()), format_name="har", destination="saved session.json")


@pytest.mark.parametrize(
    ("error", "message"),
    [(ValueError("unsupported format"), "unsupported format"), (OSError("disk full"), "Export failed (disk full).")],
)
def test_export_reports_adapter_errors(session_context, error, message):
    service, _, export, _ = session_context
    export.side_effect = error
    assert service.export(["json", "file.json"]) == message


def test_session_save_uses_json_and_keeps_journal(session_context):
    service, journal, export, _ = session_context
    before = journal.list_entries()
    assert service.session(["SAVE", "saved", "session.json"]) == "Saved session snapshot to saved session.json"
    export.assert_called_once_with(list(before), format_name="json", destination="saved session.json")
    assert journal.list_entries() == before


def test_session_save_reports_io_failure(session_context):
    service, _, export, _ = session_context
    export.side_effect = OSError("disk full")
    assert service.session(["save", "file.json"]) == "Session save failed (disk full)."


def test_session_load_replaces_journal_only_after_success(session_context):
    service, journal, _, load = session_context
    assert service.session(["LOAD", "saved", "session.json"]) == "Loaded session snapshot from saved session.json"
    load.assert_called_once_with("saved session.json")
    assert list(journal.list_entries()) == load.return_value


@pytest.mark.parametrize("error", [OSError("missing"), ValueError("invalid"), json.JSONDecodeError("bad JSON", "{", 1)])
def test_failed_load_preserves_existing_journal(session_context, error):
    service, journal, _, load = session_context
    before = journal.list_entries()
    load.side_effect = error
    assert service.session(["load", "file.json"]) == f"Session load failed ({error})."
    assert journal.list_entries() == before


def test_unknown_session_action_does_not_touch_adapters(session_context):
    service, _, export, load = session_context
    assert service.session(["delete", "file.json"]) == "Usage: session <save|load> <path>"
    export.assert_not_called()
    load.assert_not_called()
