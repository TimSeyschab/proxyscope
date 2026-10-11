from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from threading import Lock

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane, TextArea

from proxyscope.contracts.events import RuntimeEvent, RuntimeStateSnapshot
from proxyscope.contracts.ports import CapturedExchange, ComponentJournal, ConfigurationEditor

MAX_VISIBLE_ITEMS = 50
MAX_LOG_ENTRIES = 500
MOCK_BODY_PREVIEW_LENGTH = 80
DETAIL_BODY_PREVIEW_BYTES = 8_192
REQUEST_COLUMNS = ("ID", "Status", "Method", "Host", "Path", "Duration")


class RuntimeEventBuffer:
    """A bounded, thread-safe projection that retains the newest runtime events."""

    def __init__(self, *, capacity: int = MAX_VISIBLE_ITEMS) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._events: list[RuntimeEvent] = []
        self._capacity = capacity
        self._lock = Lock()

    def append(self, event: RuntimeEvent) -> None:
        with self._lock:
            self._events.append(event)
            del self._events[: -self._capacity]

    def entries(self) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            return tuple(self._events)


class RuntimeLogBuffer:
    """A bounded, thread-safe log history for the terminal UI."""

    def __init__(self, *, capacity: int = MAX_LOG_ENTRIES) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._entries: list[str] = []
        self._capacity = capacity
        self._lock = Lock()

    def append(self, entry: str) -> None:
        with self._lock:
            self._entries.append(entry)
            del self._entries[: -self._capacity]

    def entries(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._entries)


class TuiLogHandler(logging.Handler):
    def __init__(self, buffer: RuntimeLogBuffer, request_refresh: Callable[[], None]) -> None:
        super().__init__()
        self._buffer = buffer
        self._request_refresh = request_refresh

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._buffer.append(self.format(record))
            self._request_refresh()
        except Exception:
            self.handleError(record)


class ProxyscopeTui(App[None]):
    """Live terminal view backed by journal snapshots and runtime events only."""

    TITLE = "proxyscope"
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("r", "show_request", "Request"),
        Binding("s", "show_response", "Response"),
        Binding("ctrl+s", "save_configuration", "Save config"),
    ]

    def __init__(
        self,
        journal: ComponentJournal,
        configuration_editor: ConfigurationEditor | None = None,
        on_configuration_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._journal = journal
        self._configuration_editor = configuration_editor
        self._on_configuration_saved = on_configuration_saved
        self._refresh_lock = Lock()
        self._refresh_pending = True
        self._event_buffer = RuntimeEventBuffer()
        self._log_buffer = RuntimeLogBuffer()
        self._log_handler = TuiLogHandler(self._log_buffer, self._request_refresh)
        self._last_entries: tuple[CapturedExchange, ...] | None = None
        self._last_events: tuple[RuntimeEvent, ...] | None = None
        self._last_logs: tuple[str, ...] | None = None
        self._selected_request_id: int | None = None
        self._detail_tab = "request"
        self._settings: dict[str, object] = {}
        self._mockserver_configuration: dict[str, object] = {}
        self._last_mockserver_configuration: dict[str, object] | None = None
        self._configuration_status = "No configuration file attached." if configuration_editor is None else ""
        self._configuration_json = "" if configuration_editor is None else configuration_editor.load_json()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="traffic"):
            with TabPane("Traffic", id="traffic"):
                with Horizontal(id="traffic-view"):
                    with Vertical(id="main-pane", classes="pane"):
                        yield Static("TRAFFIC", id="main-title", classes="pane-title")
                        yield DataTable(id="requests")
                    with Vertical(id="detail-pane", classes="pane"):
                        yield Static("DETAIL", id="detail-title", classes="pane-title")
                        yield Static(id="detail-tabs")
                        with VerticalScroll(id="detail-scroll"):
                            yield Static(id="detail-body")
            with TabPane("Events", id="events-view"):
                yield Static(id="events", classes="pane")
            with TabPane("Logs", id="logs-view"):
                yield Static(id="logs", classes="pane")
            with TabPane("Mockserver Rules", id="mockserver-rules"):
                yield Static(id="mockserver-rules-content", classes="pane")
            with TabPane("Configuration", id="configuration"):
                yield TextArea.code_editor(
                    self._configuration_json,
                    language="json",
                    id="configuration-editor",
                    read_only=self._configuration_editor is None,
                )
                yield Static(self._configuration_status, id="configuration-status")
        with Vertical(id="status-pane"):
            yield Static(id="status-line")
            yield Static(id="config-line")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#requests", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns(*REQUEST_COLUMNS)
        self._refresh_if_needed()
        table.focus()
        self.set_interval(0.25, self._refresh_if_needed)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        row_key = event.row_key.value
        if row_key is None:
            self._selected_request_id = None
            self._refresh_detail()
            return
        try:
            self._selected_request_id = int(row_key)
        except ValueError:
            self._selected_request_id = None
        self._refresh_detail()

    def action_show_request(self) -> None:
        self._detail_tab = "request"
        self._refresh_detail()

    def action_show_response(self) -> None:
        self._detail_tab = "response"
        self._refresh_detail()

    def action_save_configuration(self) -> None:
        if self._configuration_editor is None:
            return
        editor = self.query_one("#configuration-editor", TextArea)
        try:
            saved_path = self._configuration_editor.save_json(editor.text)
        except ValueError as exc:
            self.query_one("#configuration-status", Static).update(f"Not saved: {exc}")
            return
        editor.load_text(self._configuration_editor.load_json())
        if self._on_configuration_saved is not None:
            self._on_configuration_saved()
        self.query_one("#configuration-status", Static).update(
            f"Saved {saved_path}. Runtime settings reloaded; startup-only changes require restart."
        )

    def handle_event(self, event: RuntimeEvent) -> None:
        self._event_buffer.append(event)
        self._request_refresh()

    @property
    def logging_handler(self) -> logging.Handler:
        return self._log_handler

    def update_runtime_snapshot(self, snapshot: RuntimeStateSnapshot) -> None:
        with self._refresh_lock:
            self._settings = dict(snapshot.settings)
            self._mockserver_configuration = dict(snapshot.mockserver_configuration)
            self._refresh_pending = True

    def _request_refresh(self) -> None:
        with self._refresh_lock:
            self._refresh_pending = True

    def _refresh_if_needed(self) -> None:
        with self._refresh_lock:
            if not self._refresh_pending:
                return
            self._refresh_pending = False
        self._refresh()

    def _refresh(self) -> None:
        with self._refresh_lock:
            settings = dict(self._settings)
            mockserver_configuration = dict(self._mockserver_configuration)
        entries = _visible_exchanges(self._journal.list_entries())
        if entries != self._last_entries:
            self._last_entries = entries
            self._refresh_requests(entries)
        events = _visible_events(self._event_buffer.entries())
        if events != self._last_events:
            self._last_events = events
            self.query_one("#events", Static).update(Text(_render_events(events)))
        logs = self._log_buffer.entries()
        if logs != self._last_logs:
            self._last_logs = logs
            self.query_one("#logs", Static).update(Text(_render_logs(logs)))
        if mockserver_configuration != self._last_mockserver_configuration:
            self._last_mockserver_configuration = mockserver_configuration
            self.query_one("#mockserver-rules-content", Static).update(
                Text(_render_mockserver_rules(mockserver_configuration))
            )
        self.query_one("#status-line", Static).update(_render_status(entries, events))
        self.query_one("#config-line", Static).update(_render_configuration_summary(settings))

    def _refresh_requests(self, entries: tuple[CapturedExchange, ...]) -> None:
        selected = self._selected_request_id
        if selected not in {entry.request_id for entry in entries}:
            selected = entries[0].request_id if entries else None
        self._selected_request_id = selected
        table = self.query_one("#requests", DataTable)
        table.clear(columns=False)
        for entry in entries:
            table.add_row(*_request_row(entry), key=str(entry.request_id))
        if selected is not None:
            table.move_cursor(
                row=next(index for index, entry in enumerate(entries) if entry.request_id == selected), animate=False
            )
        self._refresh_detail()

    def _refresh_detail(self) -> None:
        entry = None if self._selected_request_id is None else self._journal.get_entry(self._selected_request_id)
        self.query_one("#detail-title", Static).update("DETAIL" if entry is None else f"DETAIL #{entry.request_id}")
        self.query_one("#detail-tabs", Static).update(
            _render_detail_tabs(self._detail_tab, entry is not None and entry.response is not None)
        )
        self.query_one("#detail-body", Static).update(Text(_render_detail(entry, self._detail_tab)))


def _request_row(entry: CapturedExchange) -> tuple[str, str, str, str, str, str]:
    response = "---" if entry.response is None else str(entry.response.status_code)
    host = entry.target_host or _host_from_url(entry.url) or "-"
    path = entry.path or _path_from_url(entry.url) or "-"
    duration = "-" if entry.duration_ms is None else f"{entry.duration_ms:.1f}ms"
    return str(entry.request_id), response, entry.method, host, path, duration


def _render_detail(entry: CapturedExchange | None, tab: str) -> str:
    if entry is None:
        return "No request selected."
    if tab == "response":
        return _render_response_detail(entry)
    headers = _format_headers(entry.headers)
    return (
        f"{entry.start_line or f'{entry.method} {entry.path}'}\n"
        f"url: {entry.url or '-'}\n"
        f"host: {entry.target_host or '-'}\n"
        f"port: {entry.target_port if entry.target_port is not None else '-'}\n"
        f"protocol: {entry.protocol}\n"
        f"client: {entry.client_ip or '-'}\n\n"
        f"headers\n{headers}\n\nbody\n{_format_body(entry.body, entry.headers)}"
    )


def _render_response_detail(entry: CapturedExchange) -> str:
    response = entry.response
    if response is None:
        return "No response captured."
    duration = "-" if entry.duration_ms is None else f"{entry.duration_ms:.1f}ms"
    size = "-" if response.body_size is None else str(response.body_size)
    return (
        f"{response.start_line or f'HTTP {response.status_code} {response.reason}'}\n"
        f"status: {response.status_code} {response.reason}\n"
        f"duration: {duration}\nsize: {size}\n\n"
        f"headers\n{_format_headers(response.headers)}\n\nbody\n{_format_body(response.body, response.headers)}"
    )


def _format_headers(headers: tuple[tuple[str, str], ...]) -> str:
    return "\n".join(f"{name}: {value}" for name, value in headers) or "<none>"


def _format_body(body: bytes | None, headers: tuple[tuple[str, str], ...]) -> str:
    if body is None:
        return "<not captured>"
    if not body:
        return "<empty>"
    content_type = _content_type(headers)
    if content_type is not None and not _is_textual_content_type(content_type):
        return f"<binary body omitted: {len(body)} bytes ({content_type})>"

    preview = body[:DETAIL_BODY_PREVIEW_BYTES].decode("utf-8", errors="replace")
    if len(body) <= DETAIL_BODY_PREVIEW_BYTES:
        return preview
    return f"{preview}\n… truncated; showing first {DETAIL_BODY_PREVIEW_BYTES} of {len(body)} bytes"


def _content_type(headers: tuple[tuple[str, str], ...]) -> str | None:
    for name, value in headers:
        if name.lower() == "content-type":
            return value.split(";", 1)[0].strip().lower() or None
    return None


def _is_textual_content_type(content_type: str) -> bool:
    return content_type.startswith("text/") or content_type in {
        "application/json",
        "application/xml",
        "application/javascript",
        "application/x-javascript",
        "application/x-www-form-urlencoded",
        "application/graphql",
    }


def _render_detail_tabs(tab: str, has_response: bool) -> str:
    response_label = "[Response]" if tab == "response" else " Response "
    if not has_response:
        response_label += " (pending)"
    request_label = "[Request]" if tab == "request" else " Request "
    return f"{request_label} | {response_label}"


def _render_events(events: Iterable[RuntimeEvent]) -> str:
    rendered = []
    for event in events:
        request = "" if event.request_id is None else f" request={event.request_id}"
        component = "" if event.component_id is None else f" component={event.component_id}"
        rendered.append(f"{event.occurred_at:%H:%M:%S} {event.event_type}{request}{component}")
    return "Events\n\n" + ("\n".join(rendered) or "No runtime events yet.")


def _render_logs(entries: Iterable[str]) -> str:
    return "Logs\n\n" + ("\n".join(entries) or "No log entries yet.")


def _render_mockserver_rules(configuration: dict[str, object]) -> str:
    scenarios = configuration.get("scenarios")
    if not isinstance(scenarios, (list, tuple)) or not scenarios:
        return "Mockserver Rules\n\nNo mock scenarios configured."

    rendered = ["Mockserver Rules", ""]
    for scenario_index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            continue
        rendered.extend(_render_mock_scenario(scenario, is_last=scenario_index == len(scenarios) - 1))
    return "\n".join(rendered)


def _render_mock_scenario(scenario: dict[str, object], *, is_last: bool) -> list[str]:
    scenario_id = _display_value(scenario.get("id"), fallback="unnamed")
    name = _display_value(scenario.get("name"), fallback=scenario_id)
    enabled = "enabled" if scenario.get("enabled") is True else "disabled"
    branch = "└─" if is_last else "├─"
    continuation = "  " if is_last else "│ "
    responses = scenario.get("responses")
    if not isinstance(responses, (list, tuple)) or not responses:
        return [f"{branch} {name} (id={scenario_id}) · {enabled}", f"{continuation}  no rules"]

    lines = [f"{branch} {name} (id={scenario_id}) · {enabled}"]
    for response_index, response in enumerate(responses):
        if not isinstance(response, dict):
            continue
        is_last_response = response_index == len(responses) - 1
        response_branch = "└─" if is_last_response else "├─"
        response_continuation = "   " if is_last_response else "│  "
        method = _display_value(response.get("method"), fallback="?")
        url = _display_value(response.get("url"), fallback="?")
        status = _display_value(response.get("status"), fallback="200")
        reason = _display_value(response.get("reason"), fallback="OK")
        response_id = _display_value(response.get("id"), fallback="unnamed")
        lines.append(f"{continuation}{response_branch} {method} {url} → {status} {reason} (id={response_id})")
        lines.append(f"{continuation}{response_continuation} body: {_mock_body_preview(response.get('body'))}")
    return lines


def _display_value(value: object, *, fallback: str) -> str:
    return value if isinstance(value, str) and value else str(value) if isinstance(value, int) else fallback


def _mock_body_preview(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "<empty>"
    normalized = " ".join(value.split())
    if len(normalized) <= MOCK_BODY_PREVIEW_LENGTH:
        return normalized
    return normalized[: MOCK_BODY_PREVIEW_LENGTH - 1] + "…"


def _render_status(entries: tuple[CapturedExchange, ...], events: tuple[RuntimeEvent, ...]) -> str:
    completed = sum(entry.response is not None for entry in entries)
    return f"CAPTURED {len(entries)}  COMPLETED {completed}  EVENTS {len(events)}"


def _render_configuration_summary(settings: dict[str, object]) -> str:
    if not settings:
        return "WAITING FOR RUNTIME SNAPSHOT"
    return "  ".join(f"{key.upper()}={value}" for key, value in sorted(settings.items()))


def _visible_exchanges(entries: Iterable[CapturedExchange]) -> tuple[CapturedExchange, ...]:
    return tuple(sorted(entries, key=lambda entry: entry.request_id, reverse=True)[:MAX_VISIBLE_ITEMS])


def _visible_events(events: Iterable[RuntimeEvent]) -> tuple[RuntimeEvent, ...]:
    return tuple(sorted(events, key=lambda event: event.occurred_at, reverse=True)[:MAX_VISIBLE_ITEMS])


def _host_from_url(url: str | None) -> str | None:
    if url is None or "://" not in url:
        return None
    return url.split("://", 1)[1].split("/", 1)[0]


def _path_from_url(url: str | None) -> str | None:
    if url is None or "://" not in url:
        return None
    parts = url.split("://", 1)[1].split("/", 1)
    return "/" + parts[1] if len(parts) == 2 else "/"
