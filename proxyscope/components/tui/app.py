from __future__ import annotations

import json
from collections.abc import Iterable
from threading import Lock

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from proxyscope.contracts.events import RuntimeEvent, RuntimeStateSnapshot
from proxyscope.contracts.ports import CapturedExchange, ComponentJournal

MAX_VISIBLE_ITEMS = 50


class RuntimeEventBuffer:
    """A bounded, thread-safe event projection for the terminal view."""

    def __init__(self, *, capacity: int = MAX_VISIBLE_ITEMS) -> None:
        self._events: list[RuntimeEvent] = []
        self._capacity = capacity
        self._lock = Lock()

    def append(self, event: RuntimeEvent) -> None:
        with self._lock:
            if len(self._events) < self._capacity:
                self._events.append(event)

    def entries(self) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            return tuple(self._events)


class ProxyscopeTui(App[None]):
    """Read-only live view driven by runtime events and journal snapshots."""

    TITLE = "proxyscope"
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "app.tcss"
    BINDINGS = [Binding("q", "quit", "Quit"), Binding("ctrl+c", "quit", "Quit")]

    def __init__(self, journal: ComponentJournal) -> None:
        super().__init__()
        self._journal = journal
        self._event_buffer = RuntimeEventBuffer()
        self._last_entries: tuple[CapturedExchange, ...] | None = None
        self._last_events: tuple[RuntimeEvent, ...] | None = None
        self._settings: dict[str, object] = {}
        self._mockserver_configuration: dict[str, object] = {}
        self._last_settings: dict[str, object] | None = None
        self._last_mockserver_configuration: dict[str, object] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent():
            with TabPane("Overview", id="overview"):
                with Horizontal(id="overview-content"):
                    yield Static(id="exchanges", classes="pane")
                    yield Static(id="events", classes="pane")
            with TabPane("Settings", id="settings"):
                yield Static(id="settings-content", classes="pane")
            with TabPane("Mockserver Rules", id="mockserver-rules"):
                yield Static(id="mockserver-rules-content", classes="pane")
        with Vertical(id="status-pane"):
            yield Static(id="status-line")
            yield Static(id="config-line")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(0.5, self._refresh)

    def handle_event(self, event: RuntimeEvent) -> None:
        self._event_buffer.append(event)

    def update_runtime_snapshot(self, snapshot: RuntimeStateSnapshot) -> None:
        self._settings = dict(snapshot.settings)
        self._mockserver_configuration = dict(snapshot.mockserver_configuration)

    def _refresh(self) -> None:
        entries = _visible_exchanges(self._journal.list_entries())
        if entries != self._last_entries:
            self._last_entries = entries
            self.query_one("#exchanges", Static).update(_render_exchanges(entries))
        events = _visible_events(self._event_buffer.entries())
        if events != self._last_events:
            self._last_events = events
            self.query_one("#events", Static).update(_render_events(events))
        if self._settings != self._last_settings:
            self._last_settings = dict(self._settings)
            self.query_one("#settings-content", Static).update(_render_json("Settings", self._settings))
        if self._mockserver_configuration != self._last_mockserver_configuration:
            self._last_mockserver_configuration = dict(self._mockserver_configuration)
            self.query_one("#mockserver-rules-content", Static).update(
                _render_json("Mockserver Rules", self._mockserver_configuration)
            )
        self.query_one("#status-line", Static).update(_render_status(entries, events))
        self.query_one("#config-line", Static).update(_render_configuration_summary(self._settings))


def _render_exchanges(entries: Iterable[CapturedExchange]) -> str:
    rendered = []
    for entry in entries:
        response = "pending" if entry.response is None else str(entry.response.status_code)
        rendered.append(f"#{entry.request_id} {entry.method} {entry.url or '<unknown>'} [{response}]")
    return "Exchanges\n\n" + ("\n".join(rendered) or "No exchanges yet.")


def _render_events(events: Iterable[RuntimeEvent]) -> str:
    rendered = []
    for event in events:
        request = "" if event.request_id is None else f" request={event.request_id}"
        component = "" if event.component_id is None else f" component={event.component_id}"
        rendered.append(f"{event.occurred_at:%H:%M:%S} {event.event_type}{request}{component}")
    return "Events\n\n" + ("\n".join(rendered) or "No runtime events yet.")


def _render_json(title: str, value: object) -> str:
    return f"{title}\n\n{json.dumps(value, indent=2, sort_keys=True, default=str)}"


def _render_status(entries: tuple[CapturedExchange, ...], events: tuple[RuntimeEvent, ...]) -> str:
    completed = sum(entry.response is not None for entry in entries)
    return f"CAPTURED {len(entries)}  COMPLETED {completed}  EVENTS {len(events)}"


def _render_configuration_summary(settings: dict[str, object]) -> str:
    if not settings:
        return "WAITING FOR RUNTIME SNAPSHOT"
    return "  ".join(f"{key.upper()}={value}" for key, value in sorted(settings.items()))


def _visible_exchanges(entries: Iterable[CapturedExchange]) -> tuple[CapturedExchange, ...]:
    return tuple(sorted(entries, key=lambda entry: entry.request_id)[:MAX_VISIBLE_ITEMS])


def _visible_events(events: Iterable[RuntimeEvent]) -> tuple[RuntimeEvent, ...]:
    return tuple(sorted(events, key=lambda event: event.occurred_at)[:MAX_VISIBLE_ITEMS])
