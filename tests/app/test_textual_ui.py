import unittest

from textual.widgets import OptionList
from textual.widgets._option_list import Option

from proxyscope.app.runtime.journal import LoggedExchange, LoggedRequestMessage, LoggedResponseMessage
from proxyscope.app.runtime.textual_ui import (
    RuntimeTextualApp,
    _focus_step_order,
    _shortcut_token_from_key_event,
    determine_runtime_layout,
)
from proxyscope.app.runtime.ui_components.rendering import format_detail_tabs, plain_text
from proxyscope.app.runtime.ui_models import (
    AuxPanelModel,
    AuxPanelTabModel,
    RequestDetailModel,
    RequestListModel,
    RuntimeScreenModel,
    StatusBarModel,
)
from proxyscope.app.runtime.ui_presenter import _build_request_rows, _format_detail


def _screen_model(
    *, width_mode: str = "detail", active_pane: str = "requests", aux_visible: bool = True
) -> RuntimeScreenModel:
    return RuntimeScreenModel(
        request_list=RequestListModel(
            title="MAIN 1/1",
            rows=[],
            selected_request_id=None,
            cursor=0,
        ),
        detail=RequestDetailModel(
            tab="request",
            text="No request selected.",
            has_response=False,
        ),
        aux=AuxPanelModel(
            visible=aux_visible,
            aux_tabs=[
                AuxPanelTabModel(
                    key="sites",
                    title="SIDEBAR:SITES",
                    items=["example.com"],
                    cursor=0,
                )
            ],
            active_key="sites",
        ),
        status_bar=StatusBarModel(message="ok", config_text="cfg"),
        main_mode="request_detail" if width_mode == "detail" else "requests",
        active_pane=active_pane,  # type: ignore[arg-type]
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
    def test_focus_order_includes_sidebar_tabs_separately(self) -> None:
        steps = _focus_step_order(
            main_mode="request_detail",
            aux_visible=True,
            aux_tabs=[
                AuxPanelTabModel(key="sites", title="SIDEBAR:SITES", items=["example.com"], cursor=0),
                AuxPanelTabModel(key="policies", title="SIDEBAR:POLICIES", items=["policy-1"], cursor=0),
            ],
        )

        self.assertEqual(
            steps,
            ["requests", "detail-request", "detail-response", "aux-sites", "aux-policies", "command"],
        )

    def test_focus_order_omits_sidebar_tabs_when_hidden(self) -> None:
        steps = _focus_step_order(
            main_mode="request_detail",
            aux_visible=False,
            aux_tabs=[
                AuxPanelTabModel(key="sites", title="SIDEBAR:SITES", items=["example.com"], cursor=0),
                AuxPanelTabModel(key="policies", title="SIDEBAR:POLICIES", items=["policy-1"], cursor=0),
            ],
        )

        self.assertEqual(steps, ["requests", "detail-request", "detail-response", "command"])


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

    def test_uppercase_character_maps_to_shortcut_token(self) -> None:
        self.assertEqual(_shortcut_token_from_key_event(key="m", character="M"), "m")
        self.assertEqual(_shortcut_token_from_key_event(key="M", character=None), "m")

    def test_lowercase_without_shift_is_not_treated_as_shortcut(self) -> None:
        self.assertIsNone(_shortcut_token_from_key_event(key="m", character="m"))


if __name__ == "__main__":
    unittest.main()
