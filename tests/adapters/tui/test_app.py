import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxyscope.components.tui.app import (
    MAX_VISIBLE_ITEMS,
    ProxyscopeTui,
    RuntimeEventBuffer,
    _render_configuration_summary,
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
            ),
        )


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
                    mockserver_configuration={"scenarios": [{"id": "offline"}]},
                )
            )
            app._refresh()

            exchanges = str(app.query_one("#exchanges").render())
            events = str(app.query_one("#events").render())
            settings = str(app.query_one("#settings-content").render())
            mockserver_rules = str(app.query_one("#mockserver-rules-content").render())
            status = str(app.query_one("#status-line").render())
            configuration = str(app.query_one("#config-line").render())

        self.assertIn("GET https://api.test/items [200]", exchanges)
        self.assertIn("exchange.completed request=1", events)
        self.assertIn('"log_level": "INFO"', settings)
        self.assertIn('"id": "offline"', mockserver_rules)
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

    def test_requires_component_ports(self) -> None:
        with self.assertRaisesRegex(ValueError, "event bus"):
            TuiComponent(ComponentContext(journal=StaticJournal()))
        with self.assertRaisesRegex(ValueError, "journal"):
            TuiComponent(ComponentContext(event_bus=object()))  # type: ignore[arg-type]

    def test_shows_the_first_fifty_exchanges_in_request_order(self) -> None:
        entries = tuple(
            CapturedExchange(request_id=request_id, method="GET", url=None, response=None)
            for request_id in range(75, 0, -1)
        )

        visible = _visible_exchanges(entries)

        self.assertEqual(len(visible), MAX_VISIBLE_ITEMS)
        self.assertEqual(visible[0].request_id, 1)
        self.assertEqual(visible[-1].request_id, 50)

    def test_event_buffer_keeps_only_the_first_fifty_events(self) -> None:
        buffer = RuntimeEventBuffer()
        started_at = datetime(2026, 1, 1, tzinfo=UTC)
        for index in range(75):
            buffer.append(ExchangeCompleted(duration_ms=1, occurred_at=started_at + timedelta(seconds=index)))

        events = buffer.entries()

        self.assertEqual(len(events), MAX_VISIBLE_ITEMS)
        self.assertEqual(events[0].occurred_at, started_at)
        self.assertEqual(events[-1].occurred_at, started_at + timedelta(seconds=49))
