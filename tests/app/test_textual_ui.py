import unittest

from proxyscope.app.runtime.journal import LoggedExchange, LoggedRequestMessage, LoggedResponseMessage
from proxyscope.app.runtime.textual_ui import _format_detail, determine_runtime_layout
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


if __name__ == "__main__":
    unittest.main()
