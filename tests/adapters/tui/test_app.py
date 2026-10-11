import asyncio
import logging
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxyscope.components.tui.app import (
    DETAIL_BODY_PREVIEW_BYTES,
    MAX_LOG_ENTRIES,
    MAX_VISIBLE_ITEMS,
    ProxyscopeTui,
    RuntimeEventBuffer,
    RuntimeLogBuffer,
    _render_configuration_summary,
    _render_detail,
    _render_mockserver_rules,
    _render_status,
    _visible_exchanges,
)
from proxyscope.components.tui.component import TuiComponent
from proxyscope.contracts.components import ComponentContext
from proxyscope.contracts.events import ExchangeCompleted, RuntimeStateSnapshot
from proxyscope.contracts.ports import CapturedExchange, CapturedResponse


class StaticJournal:
    def get_entry(self, request_id: int) -> CapturedExchange | None:
        return next((entry for entry in self.list_entries() if entry.request_id == request_id), None)

    def list_entries(self) -> tuple[CapturedExchange, ...]:
        return (
            CapturedExchange(
                request_id=1,
                method="GET",
                url="https://api.test/items",
                response=CapturedResponse(200, "OK", (), None, 0),
                path="/items",
                start_line="GET /items HTTP/1.1",
                target_host="api.test",
            ),
        )


class MutableJournal:
    def __init__(self, entries: tuple[CapturedExchange, ...]) -> None:
        self.entries = entries

    def get_entry(self, request_id: int) -> CapturedExchange | None:
        return next((entry for entry in self.entries if entry.request_id == request_id), None)

    def list_entries(self) -> tuple[CapturedExchange, ...]:
        return self.entries


class InMemoryConfigurationEditor:
    def __init__(self, content: str = '{"schema_version": 1}\n') -> None:
        self.content = content
        self.saved: list[str] = []

    def load_json(self) -> str:
        return self.content

    def save_json(self, content: str) -> str:
        self.saved.append(content)
        return "config.json"


class _RejectingConfigurationEditor(InMemoryConfigurationEditor):
    def save_json(self, content: str) -> str:
        raise ValueError("settings.log_level has unsupported value: INVALID")


class TestTuiComponent(unittest.TestCase):
    def test_disables_textual_command_palette(self) -> None:
        self.assertFalse(ProxyscopeTui.ENABLE_COMMAND_PALETTE)

    def test_renders_journal_entries_and_runtime_events(self) -> None:
        asyncio.run(self._assert_rendered_content())

    async def _assert_rendered_content(self) -> None:
        component = TuiComponent(ComponentContext(event_bus=object(), journal=StaticJournal()))  # type: ignore[arg-type]
        app = component.app
        async with app.run_test() as pilot:
            await pilot.pause()
            component.handle_event(ExchangeCompleted(request_id=1, duration_ms=12.5))
            component.handle_event(
                RuntimeStateSnapshot(
                    correlation_id="snapshot",
                    settings={"log_level": "INFO"},
                    mockserver_configuration={
                        "scenarios": (
                            {
                                "id": "offline",
                                "name": "Offline API",
                                "enabled": True,
                                "responses": [
                                    {
                                        "id": "health",
                                        "method": "GET",
                                        "url": "https://api.test/health",
                                        "status": 503,
                                        "reason": "Unavailable",
                                        "body": "temporarily offline",
                                    }
                                ],
                            },
                        )
                    },
                )
            )
            app._refresh()

            requests = app.query_one("#requests")
            detail = str(app.query_one("#detail-body").render())
            events = str(app.query_one("#events").render())
            logs = str(app.query_one("#logs").render())
            mockserver_rules = str(app.query_one("#mockserver-rules-content").render())
            status = str(app.query_one("#status-line").render())
            configuration = str(app.query_one("#config-line").render())

        self.assertEqual(requests.row_count, 1)
        self.assertIn("GET /items", detail)
        self.assertIn("exchange.completed request=1", events)
        self.assertEqual(logs, "Logs\n\nNo log entries yet.")
        self.assertIn("Offline API (id=offline) · enabled", mockserver_rules)
        self.assertIn("GET https://api.test/health → 503 Unavailable (id=health)", mockserver_rules)
        self.assertEqual(status, "CAPTURED 1  COMPLETED 1  EVENTS 1")
        self.assertEqual(configuration, "LOG_LEVEL=INFO")

    def test_uses_the_legacy_operational_palette(self) -> None:
        stylesheet = (Path(__file__).parents[3] / "proxyscope" / "components" / "tui" / "app.tcss").read_text()

        self.assertEqual(ProxyscopeTui.CSS_PATH, "app.tcss")
        for color in ("#101315", "#171c20", "#465158", "#d9a94f"):
            self.assertIn(color, stylesheet)
        self.assertIn("#status-pane", stylesheet)

    def test_renders_compact_runtime_status_and_configuration(self) -> None:
        entry = StaticJournal().list_entries()[0]
        event = ExchangeCompleted(request_id=entry.request_id, duration_ms=1)

        self.assertEqual(_render_status((entry,), (event,)), "CAPTURED 1  COMPLETED 1  EVENTS 1")
        self.assertEqual(_render_configuration_summary({}), "WAITING FOR RUNTIME SNAPSHOT")
        self.assertEqual(
            _render_configuration_summary({"mitm": True, "log_level": "INFO"}), "LOG_LEVEL=INFO  MITM=True"
        )

    def test_renders_mockserver_rules_with_a_truncated_body_preview(self) -> None:
        rules = _render_mockserver_rules(
            {
                "scenarios": [
                    {
                        "id": "demo",
                        "name": "Demo API",
                        "enabled": False,
                        "responses": [
                            {
                                "id": "items",
                                "method": "POST",
                                "url": "https://api.test/items",
                                "status": 201,
                                "reason": "Created",
                                "body": "x" * 100,
                            }
                        ],
                    }
                ]
            }
        )

        self.assertIn("Demo API (id=demo) · disabled", rules)
        self.assertIn("POST https://api.test/items → 201 Created (id=items)", rules)
        self.assertIn("body: " + "x" * 79 + "…", rules)
        self.assertNotIn("x" * 100, rules)

    def test_requires_component_ports(self) -> None:
        with self.assertRaisesRegex(ValueError, "event bus"):
            TuiComponent(ComponentContext(journal=StaticJournal()))
        with self.assertRaisesRegex(ValueError, "journal"):
            TuiComponent(ComponentContext(event_bus=object()))  # type: ignore[arg-type]

    def test_saves_configuration_from_the_editor(self) -> None:
        configuration_editor = InMemoryConfigurationEditor()
        app = ProxyscopeTui(StaticJournal(), configuration_editor)

        asyncio.run(self._assert_configuration_is_saved(app, configuration_editor))

    def test_displays_a_configuration_validation_error(self) -> None:
        app = ProxyscopeTui(StaticJournal(), _RejectingConfigurationEditor())

        asyncio.run(self._assert_configuration_error_is_displayed(app))

    async def _assert_configuration_is_saved(
        self,
        app: ProxyscopeTui,
        configuration_editor: InMemoryConfigurationEditor,
    ) -> None:
        async with app.run_test():
            editor = app.query_one("#configuration-editor")
            editor.load_text('{"schema_version": 1, "settings": {}}\n')
            app.action_save_configuration()
            status = str(app.query_one("#configuration-status").render())

        self.assertEqual(configuration_editor.saved, ['{"schema_version": 1, "settings": {}}\n'])
        self.assertEqual(
            status,
            "Saved config.json. Runtime settings reloaded; startup-only changes require restart.",
        )

    def test_configuration_save_requests_a_fresh_runtime_snapshot(self) -> None:
        requests: list[None] = []
        app = ProxyscopeTui(
            StaticJournal(),
            InMemoryConfigurationEditor(),
            on_configuration_saved=lambda: requests.append(None),
        )

        asyncio.run(self._assert_configuration_save_requests_snapshot(app))

        self.assertEqual(requests, [None])

    async def _assert_configuration_save_requests_snapshot(self, app: ProxyscopeTui) -> None:
        async with app.run_test():
            app.action_save_configuration()

    async def _assert_configuration_error_is_displayed(self, app: ProxyscopeTui) -> None:
        async with app.run_test():
            app.action_save_configuration()
            status = str(app.query_one("#configuration-status").render())

        self.assertEqual(status, "Not saved: settings.log_level has unsupported value: INVALID")

    def test_shows_the_newest_fifty_exchanges_first(self) -> None:
        entries = tuple(
            CapturedExchange(request_id=request_id, method="GET", url=None, response=None)
            for request_id in range(75, 0, -1)
        )

        visible = _visible_exchanges(entries)

        self.assertEqual(len(visible), MAX_VISIBLE_ITEMS)
        self.assertEqual(visible[0].request_id, 75)
        self.assertEqual(visible[-1].request_id, 26)

    def test_event_buffer_keeps_only_the_latest_fifty_events(self) -> None:
        buffer = RuntimeEventBuffer()
        started_at = datetime(2026, 1, 1, tzinfo=UTC)
        for index in range(75):
            buffer.append(ExchangeCompleted(duration_ms=1, occurred_at=started_at + timedelta(seconds=index)))

        events = buffer.entries()

        self.assertEqual(len(events), MAX_VISIBLE_ITEMS)
        self.assertEqual(events[0].occurred_at, started_at + timedelta(seconds=25))
        self.assertEqual(events[-1].occurred_at, started_at + timedelta(seconds=74))

    def test_event_buffer_rejects_non_positive_capacity(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            RuntimeEventBuffer(capacity=0)

    def test_log_buffer_retains_the_latest_five_hundred_entries(self) -> None:
        buffer = RuntimeLogBuffer()
        for index in range(MAX_LOG_ENTRIES + 25):
            buffer.append(f"entry {index}")

        entries = buffer.entries()

        self.assertEqual(len(entries), MAX_LOG_ENTRIES)
        self.assertEqual(entries[0], "entry 25")
        self.assertEqual(entries[-1], f"entry {MAX_LOG_ENTRIES + 24}")

    def test_log_buffer_rejects_non_positive_capacity(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            RuntimeLogBuffer(capacity=0)

    def test_logging_handler_renders_records_in_the_logs_tab(self) -> None:
        app = ProxyscopeTui(StaticJournal())

        asyncio.run(self._assert_log_record_is_rendered(app))

    async def _assert_log_record_is_rendered(self, app: ProxyscopeTui) -> None:
        async with app.run_test():
            record = logging.LogRecord("proxyscope.test", logging.INFO, __file__, 0, "captured log", (), None)
            app.logging_handler.handle(record)
            app._refresh_if_needed()
            logs = str(app.query_one("#logs").render())

        self.assertIn("captured log", logs)

    def test_renders_request_and_response_detail_from_journal_snapshot(self) -> None:
        entry = CapturedExchange(
            request_id=7,
            method="POST",
            url="https://api.test/items",
            response=CapturedResponse(201, "Created", (("X-Response", "yes"),), b"response", 8, "HTTP/1.1 201 Created"),
            path="/items",
            start_line="POST /items HTTP/1.1",
            headers=(("X-Request", "yes"),),
            body=b"request",
            client_ip="127.0.0.1",
            target_host="api.test",
            target_port=443,
            protocol="https",
            duration_ms=12.5,
        )

        self.assertIn("X-Request: yes", _render_detail(entry, "request"))
        response = _render_detail(entry, "response")
        self.assertIn("HTTP/1.1 201 Created", response)
        self.assertIn("X-Response: yes", response)
        self.assertIn("response", response)

    def test_omits_binary_response_bodies_and_truncates_text_bodies(self) -> None:
        binary_body = b"\x89PNG\r\n\x1a\n" + b"x" * 100
        binary_entry = CapturedExchange(
            request_id=8,
            method="GET",
            url="https://api.test/image.png",
            response=CapturedResponse(
                200,
                "OK",
                (("Content-Type", "image/png"),),
                binary_body,
                len(binary_body),
            ),
        )
        text_entry = CapturedExchange(
            request_id=9,
            method="GET",
            url="https://api.test/large-text",
            response=CapturedResponse(
                200,
                "OK",
                (("Content-Type", "text/plain; charset=utf-8"),),
                b"x" * (DETAIL_BODY_PREVIEW_BYTES + 1),
                DETAIL_BODY_PREVIEW_BYTES + 1,
            ),
        )

        binary_detail = _render_detail(binary_entry, "response")
        text_detail = _render_detail(text_entry, "response")

        self.assertIn(f"<binary body omitted: {len(binary_body)} bytes (image/png)>", binary_detail)
        self.assertIn(
            f"… truncated; showing first {DETAIL_BODY_PREVIEW_BYTES} of {DETAIL_BODY_PREVIEW_BYTES + 1} bytes",
            text_detail,
        )

    def test_displays_detail_bodies_as_literal_text(self) -> None:
        entry = CapturedExchange(
            request_id=10,
            method="GET",
            url="https://api.test/markup",
            response=CapturedResponse(
                200,
                "OK",
                (("Content-Type", "text/plain"),),
                b"[invalid markup",
                15,
            ),
        )
        app = ProxyscopeTui(MutableJournal((entry,)))

        asyncio.run(self._assert_literal_detail_body(app))

    async def _assert_literal_detail_body(self, app: ProxyscopeTui) -> None:
        async with app.run_test() as pilot:
            await pilot.press("s")
            self.assertIn("[invalid markup", str(app.query_one("#detail-body").render()))

    def test_selection_and_detail_follow_event_driven_journal_snapshots(self) -> None:
        asyncio.run(self._assert_selection_follows_live_journal())

    async def _assert_selection_follows_live_journal(self) -> None:
        first = CapturedExchange(1, "GET", "http://api.test/one", None, path="/one", start_line="GET /one HTTP/1.1")
        second = CapturedExchange(
            2,
            "POST",
            "http://api.test/two",
            CapturedResponse(202, "Accepted", (), b"two", 3),
            path="/two",
            start_line="POST /two HTTP/1.1",
        )
        journal = MutableJournal((first, second))
        app = ProxyscopeTui(journal)
        async with app.run_test() as pilot:
            table = app.query_one("#requests")
            table.focus()
            table.move_cursor(row=1, animate=False)
            await pilot.pause()
            self.assertEqual(app._selected_request_id, 1)

            table.move_cursor(row=0, animate=False)
            await pilot.pause()
            self.assertEqual(app._selected_request_id, 2)
            self.assertIn("POST /two HTTP/1.1", str(app.query_one("#detail-body").render()))

            await pilot.press("s")
            self.assertEqual(app._detail_tab, "response")
            self.assertIn("202 Accepted", str(app.query_one("#detail-body").render()))

            journal.entries = (first,)
            app.handle_event(ExchangeCompleted(request_id=1, duration_ms=1))
            app._refresh_if_needed()
            self.assertEqual(app._selected_request_id, 1)
            self.assertIn("No response captured.", str(app.query_one("#detail-body").render()))

            await pilot.press("r")
            self.assertIn("GET /one HTTP/1.1", str(app.query_one("#detail-body").render()))
