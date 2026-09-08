from dataclasses import replace
from unittest.mock import patch

import pytest

from proxyscope.application.journal import RequestJournal
from proxyscope.application.requests.service import RequestApplicationService, RequestFilter
from tests.support.exchanges import recorded_exchange


@pytest.fixture
def requests():
    journal = RequestJournal()
    journal.replace_entries(
        [
            replace(recorded_exchange(), request_id=1),
            replace(recorded_exchange(method="POST", status=404), request_id=2),
            replace(recorded_exchange(host=None, status=None), request_id=3),
        ]
    )
    return RequestApplicationService(journal)


@pytest.mark.parametrize(
    ("arguments", "expected_ids"),
    [
        (["host", "API.TEST"], [2, 1]),
        (["method", "post"], [2]),
        (["status", "200"], [1]),
        (["status", "0"], []),
        (["text", "RESPONSE-MARKER"], [2, 1]),
    ],
)
def test_filters_select_matching_requests(requests, arguments, expected_ids):
    requests.apply_filter(arguments)
    assert [entry.request_id for entry in requests.list_entries()] == expected_ids
    assert requests.filter_summary != "off"
    requests.apply_filter([arguments[0], "clear"])
    assert requests.filter_summary == "off"
    assert [entry.request_id for entry in requests.list_entries()] == [3, 2, 1]


def test_combined_filters_require_every_condition(requests):
    for arguments in (["host", "api.test"], ["method", "POST"], ["status", "404"], ["text", "items"]):
        requests.apply_filter(arguments)
    assert requests.filter_summary == "host=api.test method=POST status=404 text=items"
    assert [entry.request_id for entry in requests.list_entries()] == [2]
    requests.apply_filter(["status", "200"])
    assert requests.list_entries() == []
    assert requests.apply_filter(["clear"]) == "Request filter cleared."
    assert len(requests.list_entries()) == 3


@pytest.mark.parametrize("field", ["host", "method", "status", "text"])
def test_missing_filter_argument_does_not_change_existing_filter(requests, field):
    requests.apply_filter(["status", "200"])
    assert requests.apply_filter([field]).startswith(f"Usage: filter {field}")
    assert requests.filter_summary == "status=200"


@pytest.mark.parametrize("arguments", [[], ["show"], ["SHOW"]])
def test_show_filter_does_not_change_selection(requests, arguments):
    assert requests.apply_filter(arguments) == "Request filter: off"


def test_invalid_filter_keeps_previous_selection(requests):
    requests.apply_filter(["status", "200"])
    assert requests.apply_filter(["status", "not-a-number"]) == "Status filter must be an integer."
    assert requests.apply_filter(["unknown"]).startswith("Usage: filter")
    assert [entry.request_id for entry in requests.list_entries()] == [1]


@pytest.mark.parametrize(
    "query",
    [
        "GET",
        "/items",
        "API.TEST",
        "192.0.2.1",
        "request-payload",
        "X-Request",
        "request-marker",
        "200",
        "response-reason",
        "response-payload",
        "X-Response",
        "response-marker",
    ],
)
def test_find_searches_request_and_response_fields(query):
    journal = RequestJournal()
    journal.replace_entries([recorded_exchange()])
    service = RequestApplicationService(journal)
    assert service.find([query]) == f"Request filter: text={query.lower()}"
    assert len(service.list_entries()) == 1


def test_find_clearing_and_missing_query(requests):
    assert requests.find([]) == "Usage: find <search text>|clear"
    requests.find(["not", "present"])
    assert requests.list_entries() == []
    assert requests.find(["CLEAR"]) == "Request filter: off"
    assert len(requests.list_entries()) == 3


@pytest.mark.parametrize(
    ("cursor", "limit", "expected_ids", "offset", "selected"),
    [
        (-5, 2, [3, 2], 0, 3),
        (1, 2, [3, 2], 0, 2),
        (99, 2, [2, 1], 1, 1),
        (1, 10, [3, 2, 1], 0, 2),
        (99, 0, [], 0, 1),
        (-1, -2, [], 0, 3),
    ],
)
def test_window_clamps_cursor_and_preserves_selection(requests, cursor, limit, expected_ids, offset, selected):
    window = requests.list_window(cursor=cursor, limit=limit)
    assert [entry.request_id for entry in window.entries] == expected_ids
    assert window.offset == offset
    assert window.selected_entry.request_id == selected
    assert window.total_count == window.all_count == 3


@pytest.mark.parametrize("limit", [0, 2])
def test_empty_window_has_no_selected_entry(limit):
    service = RequestApplicationService(RequestJournal())
    window = service.list_window(cursor=10, limit=limit)
    assert window.entries == []
    assert window.selected_entry is None
    assert window.offset == window.total_count == window.all_count == 0


def test_filtered_window_reports_unfiltered_count(requests):
    requests.apply_filter(["status", "200"])
    window = requests.list_window(cursor=10, limit=1)
    assert window.total_count == 1
    assert window.all_count == 3
    assert window.entries == [window.selected_entry]
    assert window.selected_entry.request_id == 1


@pytest.mark.parametrize(
    ("cursor", "limit", "expected_ids", "offset", "selected"),
    [(0, 3, [10, 9, 8], 0, 10), (4, 3, [7, 6, 5], 3, 6), (9, 3, [3, 2, 1], 7, 1), (5, 4, [7, 6, 5, 4], 3, 5)],
)
def test_window_centers_selection_using_a_single_journal_snapshot(cursor, limit, expected_ids, offset, selected):
    journal = RequestJournal()
    entry = recorded_exchange()
    journal.replace_entries([replace(entry, request_id=identifier) for identifier in range(1, 11)])
    service = RequestApplicationService(journal)
    with patch.object(journal, "list_entries", wraps=journal.list_entries) as snapshot:
        window = service.list_window(cursor=cursor, limit=limit)
        snapshot.assert_called_once_with()
    assert [entry.request_id for entry in window.entries] == expected_ids
    assert window.offset == offset
    assert window.selected_entry.request_id == selected
    assert window.total_count == window.all_count == 10


def test_filtered_empty_window_preserves_all_count(requests):
    requests.apply_filter(["status", "999"])
    window = requests.list_window(cursor=10, limit=3)
    assert window.entries == []
    assert window.selected_entry is None
    assert window.total_count == window.offset == 0
    assert window.all_count == 3


def test_clear_and_returned_lists_do_not_leak_mutations(requests):
    requests.list_all_entries().clear()
    assert len(requests.list_all_entries()) == 3
    assert requests.clear() == "Request list cleared."
    assert requests.list_all_entries() == []


def test_site_counts_are_independent_snapshots_and_ranked(requests):
    assert requests.top_sites_summary() == "No sites recorded yet."
    for host in ("one.test", "two.test", "two.test"):
        requests.record_site_visit(host)
    requests.site_counter().clear()
    assert requests.site_names() == ["two.test", "one.test"]
    assert requests.top_sites_summary(limit=1) == "Top sites: two.test (2)"


@pytest.mark.parametrize(
    ("filter_value", "entry", "expected"),
    [
        (RequestFilter(), recorded_exchange(host=None, status=None), True),
        (RequestFilter(host="api.test"), recorded_exchange(host=None), False),
        (RequestFilter(status_code=200), recorded_exchange(status=None), False),
        (RequestFilter(status_code=200), recorded_exchange(status=404), False),
        (RequestFilter(text="missing"), recorded_exchange(status=None), False),
    ],
)
def test_filter_conditions_with_missing_host_and_response(filter_value, entry, expected):
    assert filter_value.matches(entry) is expected
