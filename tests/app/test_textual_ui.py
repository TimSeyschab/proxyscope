import unittest

from textual.widgets import OptionList
from textual.widgets._option_list import Option

from proxyscope.app.runtime.journal import LoggedExchange, LoggedRequestMessage, LoggedResponseMessage
from proxyscope.app.runtime.textual_ui import (
    _detail_signature,
    _format_detail,
    _request_rows_signature,
    determine_runtime_layout,
)
from proxyscope.app.runtime.tui import AuxPanelTabModel, RuntimeScreenModel


def _screen_model(*, width_mode: str = "detail", active_pane: str = "requests", aux_visible: bool = True) -> RuntimeScreenModel:
    return RuntimeScreenModel(
        request_title="MAIN 1/1",
        request_entries=[],
        request_cursor=0,
        request_scroll=0,
        request_detail_scroll=0,
        response_detail_scroll=0,
        main_mode="request_detail" if width_mode == "detail" else "requests",
        active_pane=active_pane,  # type: ignore[arg-type]
        detail_tab="request",
        aux_visible=aux_visible,
        aux_tabs=[
            AuxPanelTabModel(
                key="sites",
                title="SIDEBAR:SITES",
                items=["example.com"],
                cursor=0,
                scroll=0,
            )
        ],
        aux_active_key="sites",
        command_buffer="",
        status_message="ok",
        config_text="cfg",
    )


class TestTextualUILayout(unittest.TestCase):
    def test_large_layout_shows_detail_and_sidebar(self) -> None:
        plan = determine_runtime_layout(width=160, model=_screen_model(active_pane="requests"))
        self.assertEqual(plan.content_layout, "horizontal")
        self.assertTrue(plan.show_detail)
        self.assertTrue(plan.show_sidebar)

    def test_medium_layout_prefers_active_sidebar_over_detail(self) -> None:
        plan = determine_runtime_layout(width=120, model=_screen_model(active_pane="aux"))
        self.assertEqual(plan.content_layout, "horizontal")
        self.assertFalse(plan.show_detail)
        self.assertTrue(plan.show_sidebar)

    def test_small_layout_stacks_content_vertically(self) -> None:
        plan = determine_runtime_layout(width=80, model=_screen_model(active_pane="detail"))
        self.assertEqual(plan.content_layout, "vertical")
        self.assertTrue(plan.show_detail)
        self.assertFalse(plan.show_sidebar)


class TestTextualUIDetailFormatting(unittest.TestCase):
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
            _request_rows_signature([pending_entry]),
            _request_rows_signature([complete_entry]),
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
            _detail_signature(base_entry, "response"),
            _detail_signature(updated_entry, "response"),
        )


class TestTextualEventCompatibility(unittest.TestCase):
    def test_option_highlighted_exposes_option_index(self) -> None:
        event = OptionList.OptionHighlighted(OptionList(), Option("alpha"), 3)

        self.assertEqual(event.option_index, 3)
        self.assertFalse(hasattr(event, "index"))


if __name__ == "__main__":
    unittest.main()
