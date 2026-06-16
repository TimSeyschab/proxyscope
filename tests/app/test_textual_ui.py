import unittest

from textual.app import App, ComposeResult
from textual.widgets import DataTable, OptionList
from textual.widgets._option_list import Option

from proxyscope.adapters.tui.components import RequestList
from proxyscope.adapters.tui.components.rendering import format_detail_tabs, plain_text
from proxyscope.adapters.tui.models import (
    RequestDetailModel,
    RequestListModel,
    RequestRowModel,
    RuntimeScreenModel,
    StatusBarModel,
    TabbedListModel,
    TabbedListTabModel,
)
from proxyscope.adapters.tui.presenter import _build_request_rows, _format_detail
from proxyscope.adapters.tui.textual import (
    RuntimeTextualApp,
    _focus_step_order,
    _shortcut_token_from_key_event,
    determine_runtime_layout,
)
from proxyscope.application.journal import LoggedExchange, LoggedRequestMessage, LoggedResponseMessage


class RequestListTestApp(App[None]):
    def compose(self) -> ComposeResult:
        yield RequestList()


def _screen_model(
    *,
    active_view: str = "traffic",
    active_pane: str = "requests",
    detail_visible: bool = False,
    detail_ratio: str = "third",
) -> RuntimeScreenModel:
    return RuntimeScreenModel(
        request_list=RequestListModel(
            title="MAIN 1/1",
            rows=[],
            selected_request_id=None,
            cursor=0,
            row_offset=0,
            follow_top=False,
        ),
        detail=RequestDetailModel(
            tab="request",
            text="No request selected.",
            has_response=False,
        ),
        detail_visible=detail_visible,
        detail_ratio=detail_ratio,  # type: ignore[arg-type]
        admin=TabbedListModel(
            tabs=[
                TabbedListTabModel(
                    key="sites",
                    title="Sites",
                    items=["example.com"],
                    cursor=0,
                )
            ],
            active_key="sites",
        ),
        status_bar=StatusBarModel(message="ok", config_text="cfg"),
        active_view=active_view,  # type: ignore[arg-type]
        active_pane=active_pane,  # type: ignore[arg-type]
    )


class TestTextualUILayout(unittest.TestCase):
    def test_large_layout_uses_horizontal_traffic_layout(self) -> None:
        plan = determine_runtime_layout(width=160, model=_screen_model(active_pane="requests"))
        self.assertEqual(plan.content_layout, "horizontal")

    def test_medium_layout_keeps_horizontal_traffic_layout(self) -> None:
        plan = determine_runtime_layout(width=120, model=_screen_model(active_pane="detail"))
        self.assertEqual(plan.content_layout, "horizontal")

    def test_small_layout_stacks_content_vertically(self) -> None:
        plan = determine_runtime_layout(width=80, model=_screen_model(active_pane="detail"))
        self.assertEqual(plan.content_layout, "vertical")


class TestTextualUIRequestList(unittest.TestCase):
    def test_new_requests_keep_view_stable_when_selection_is_not_first_row(self) -> None:
        async def run_test() -> None:
            app = RequestListTestApp()

            async with app.run_test(size=(100, 8)) as pilot:
                request_list = app.query_one(RequestList)
                table = app.query_one(DataTable)

                request_list.render_model(_request_list_model([30, *range(20, 0, -1)], cursor=1), active=True)
                table.scroll_to(y=0, animate=False, immediate=True, force=True)
                await pilot.pause()

                request_list.render_model(_request_list_model([50, 40, 30, *range(20, 0, -1)], cursor=3), active=True)
                await pilot.pause()

                self.assertEqual(table.cursor_row, 3)
                self.assertEqual(table.scroll_y, 2)

        import asyncio

        asyncio.run(run_test())

    def test_new_requests_do_not_scroll_down_when_selection_is_first_row(self) -> None:
        async def run_test() -> None:
            app = RequestListTestApp()

            async with app.run_test(size=(100, 8)) as pilot:
                request_list = app.query_one(RequestList)
                table = app.query_one(DataTable)

                request_list.render_model(_request_list_model([30, *range(20, 0, -1)], cursor=0), active=True)
                table.scroll_to(y=0, animate=False, immediate=True, force=True)
                await pilot.pause()

                request_list.render_model(_request_list_model([50, 40, 30, *range(20, 0, -1)], cursor=2), active=True)
                await pilot.pause()

                self.assertEqual(table.cursor_row, 2)
                self.assertEqual(table.scroll_y, 0)

        import asyncio

        asyncio.run(run_test())

    def test_request_window_cursor_is_mapped_to_visible_table_row(self) -> None:
        async def run_test() -> None:
            app = RequestListTestApp()

            async with app.run_test(size=(100, 8)) as pilot:
                request_list = app.query_one(RequestList)
                table = app.query_one(DataTable)

                request_list.render_model(
                    _request_list_model([90, 80, 70], cursor=11, row_offset=10),
                    active=True,
                )
                await pilot.pause()

                self.assertEqual(table.cursor_row, 1)

        import asyncio

        asyncio.run(run_test())

    def test_follow_top_keeps_cursor_and_scroll_at_first_row(self) -> None:
        async def run_test() -> None:
            app = RequestListTestApp()

            async with app.run_test(size=(100, 8)) as pilot:
                request_list = app.query_one(RequestList)
                table = app.query_one(DataTable)

                request_list.render_model(_request_list_model([30, *range(20, 0, -1)], cursor=0), active=True)
                await pilot.pause()

                request_list.render_model(
                    _request_list_model([50, 40, 30, *range(20, 0, -1)], cursor=0, follow_top=True),
                    active=True,
                )
                await pilot.pause()

                self.assertEqual(table.cursor_row, 0)
                self.assertEqual(table.scroll_y, 0)

        import asyncio

        asyncio.run(run_test())


class TestTextualUIDetailFormatting(unittest.TestCase):
    def test_plain_text_preserves_markup_like_content(self) -> None:
        rendered = plain_text("DETAIL [response] body=[abc]")

        self.assertEqual(rendered.plain, "DETAIL [response] body=[abc]")

    def test_detail_tabs_show_response_target(self) -> None:
        tabs = format_detail_tabs(detail_tab="request", has_response=True)

        self.assertEqual(tabs, "[Request] |  Response ")

    def test_detail_tabs_mark_pending_response(self) -> None:
        tabs = format_detail_tabs(detail_tab="request", has_response=False)

        self.assertEqual(tabs, "[Request] |  Response (pending) ")

    def test_response_detail_renders_status_and_preview(self) -> None:
        entry = LoggedExchange(
            request_id=1,
            started_at=0.0,
            finished_at=1.0,
            duration_ms=12.5,
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=443,
            protocol="https-mitm",
            request=LoggedRequestMessage(
                method="GET",
                path="/",
                start_line="GET / HTTP/1.1",
                headers=(("Host", "example.com"),),
                body_preview="",
                body=b"",
            ),
            response=LoggedResponseMessage(
                status_code=200,
                reason="OK",
                start_line="HTTP/1.1 200 OK",
                headers=(("Content-Type", "text/plain"),),
                body_preview="hello",
                body_size=5,
            ),
        )

        detail = _format_detail(entry, "response")

        self.assertIn("HTTP/1.1 200 OK", detail)
        self.assertIn("status: 200 OK", detail)
        self.assertIn("body\nhello", detail)

    def test_request_rows_signature_changes_when_response_status_changes(self) -> None:
        pending_entry = LoggedExchange(
            request_id=1,
            started_at=0.0,
            finished_at=None,
            duration_ms=None,
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
            request=LoggedRequestMessage(
                method="GET",
                path="/",
                start_line="GET / HTTP/1.1",
                headers=(),
                body_preview="",
                body=b"",
            ),
            response=None,
        )
        complete_entry = LoggedExchange(
            request_id=1,
            started_at=0.0,
            finished_at=1.0,
            duration_ms=3.4,
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
            request=pending_entry.request,
            response=LoggedResponseMessage(
                status_code=201,
                reason="Created",
                start_line="HTTP/1.1 201 Created",
                headers=(),
                body_preview="done",
                body_size=4,
            ),
        )

        self.assertNotEqual(
            _build_request_rows([pending_entry]),
            _build_request_rows([complete_entry]),
        )

    def test_detail_signature_changes_when_response_preview_changes(self) -> None:
        base_entry = LoggedExchange(
            request_id=1,
            started_at=0.0,
            finished_at=1.0,
            duration_ms=5.0,
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=443,
            protocol="https-mitm",
            request=LoggedRequestMessage(
                method="GET",
                path="/",
                start_line="GET / HTTP/1.1",
                headers=(),
                body_preview="",
                body=b"",
            ),
            response=LoggedResponseMessage(
                status_code=200,
                reason="OK",
                start_line="HTTP/1.1 200 OK",
                headers=(),
                body_preview="alpha",
                body_size=5,
            ),
        )
        updated_entry = LoggedExchange(
            request_id=1,
            started_at=0.0,
            finished_at=1.0,
            duration_ms=5.0,
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=443,
            protocol="https-mitm",
            request=base_entry.request,
            response=LoggedResponseMessage(
                status_code=200,
                reason="OK",
                start_line="HTTP/1.1 200 OK",
                headers=(),
                body_preview="beta",
                body_size=4,
            ),
        )

        self.assertNotEqual(
            _format_detail(base_entry, "response"),
            _format_detail(updated_entry, "response"),
        )


class TestTextualUIFocusOrder(unittest.TestCase):
    def test_focus_order_uses_admin_tabs_on_admin_view(self) -> None:
        steps = _focus_step_order(
            active_view="admin",
            detail_visible=False,
            admin_tabs=[
                TabbedListTabModel(key="sites", title="Sites", items=["example.com"], cursor=0),
                TabbedListTabModel(key="policies", title="Policies", items=["policy-1"], cursor=0),
            ],
        )

        self.assertEqual(
            [step.key for step in steps],
            ["admin:sites", "admin:policies"],
        )

    def test_focus_order_uses_only_requests_when_detail_is_closed(self) -> None:
        steps = _focus_step_order(
            active_view="traffic",
            detail_visible=False,
            admin_tabs=[
                TabbedListTabModel(key="sites", title="Sites", items=["example.com"], cursor=0),
                TabbedListTabModel(key="policies", title="Policies", items=["policy-1"], cursor=0),
            ],
        )

        self.assertEqual([step.key for step in steps], ["traffic:requests"])

    def test_focus_order_uses_request_and_detail_when_detail_is_open(self) -> None:
        steps = _focus_step_order(
            active_view="traffic",
            detail_visible=True,
            admin_tabs=[
                TabbedListTabModel(key="sites", title="Sites", items=["example.com"], cursor=0),
                TabbedListTabModel(key="policies", title="Policies", items=["policy-1"], cursor=0),
            ],
        )

        self.assertEqual(
            [step.key for step in steps],
            ["traffic:requests", "traffic:detail:request", "traffic:detail:response"],
        )


class TestTextualUIBindings(unittest.TestCase):
    def test_runtime_bindings_have_unique_keys(self) -> None:
        keys = [binding.key for binding in RuntimeTextualApp.BINDINGS]

        self.assertEqual(len(keys), len(set(keys)))

    def test_runtime_bindings_are_priority_shortcuts(self) -> None:
        self.assertTrue(all(binding.priority for binding in RuntimeTextualApp.BINDINGS))


class TestTextualEventCompatibility(unittest.TestCase):
    def test_option_highlighted_exposes_option_index(self) -> None:
        event = OptionList.OptionHighlighted(OptionList(), Option("alpha"), 3)

        self.assertEqual(event.option_index, 3)
        self.assertFalse(hasattr(event, "index"))


class TestTextualShortcutParsing(unittest.TestCase):
    def test_shift_plus_letter_maps_to_shortcut_token(self) -> None:
        self.assertEqual(_shortcut_token_from_key_event(key="shift+m", character=None), "m")
        self.assertEqual(_shortcut_token_from_key_event(key="shift+t", character=None), "t")

    def test_shift_plus_number_maps_to_view_shortcut_token(self) -> None:
        self.assertEqual(_shortcut_token_from_key_event(key="shift+1", character=None), "!")
        self.assertEqual(_shortcut_token_from_key_event(key="!", character="!"), "!")
        self.assertEqual(_shortcut_token_from_key_event(key="shift+2", character=None), "@")
        self.assertEqual(_shortcut_token_from_key_event(key='"', character='"'), "@")
        self.assertEqual(_shortcut_token_from_key_event(key="@", character="@"), "@")

    def test_uppercase_character_maps_to_shortcut_token(self) -> None:
        self.assertEqual(_shortcut_token_from_key_event(key="m", character="M"), "m")
        self.assertEqual(_shortcut_token_from_key_event(key="M", character=None), "m")

    def test_lowercase_without_shift_is_not_treated_as_shortcut(self) -> None:
        self.assertIsNone(_shortcut_token_from_key_event(key="m", character="m"))


def _request_list_model(
    request_ids: list[int],
    *,
    cursor: int,
    row_offset: int = 0,
    follow_top: bool = False,
) -> RequestListModel:
    rows = [
        RequestRowModel(
            request_id=request_id,
            cells=(
                str(request_id),
                "---",
                "GET",
                "example.com",
                f"/{request_id}",
                "-",
            ),
        )
        for request_id in request_ids
    ]
    return RequestListModel(
        title=f"MAIN {len(rows)}/{len(rows)}",
        rows=rows,
        cursor=cursor,
        row_offset=row_offset,
        follow_top=follow_top,
        selected_request_id=rows[cursor - row_offset].request_id if rows else None,
    )


if __name__ == "__main__":
    unittest.main()
