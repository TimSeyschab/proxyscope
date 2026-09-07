from typing import cast

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from proxyscope.adapters.tui.components.contracts import ComponentFocus, detail_focus
from proxyscope.adapters.tui.components.rendering import format_detail_tabs, plain_text
from proxyscope.adapters.tui.models import DetailTab, RequestDetailModel


class RequestDetailPane(Vertical):
    _target_prefix = "detail:"

    class Focused(Message):
        pass

    @staticmethod
    def focus_target(tab_key: str) -> ComponentFocus:
        return detail_focus(tab_key)

    @classmethod
    def owns_focus(cls, focus: ComponentFocus) -> bool:
        return focus.target_id.value.startswith(cls._target_prefix)

    @classmethod
    def tab_key_from_focus(cls, focus: ComponentFocus) -> DetailTab:
        return cast(DetailTab, focus.target_id.value.removeprefix(cls._target_prefix))

    def __init__(self) -> None:
        super().__init__(id="detail-pane", classes="pane")
        self._detail_cache = ""

    def compose(self) -> ComposeResult:
        yield Static(id="detail-title", classes="pane-title")
        yield Static(id="detail-tabs")
        with VerticalScroll(id="detail-scroll", can_focus=True):
            yield Static(id="detail-body")

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self.post_message(self.Focused())

    def render_model(self, model: RequestDetailModel, *, active: bool) -> None:
        self.set_class(active, "-active")
        title_text = f"DETAIL [{model.tab}]"
        title = self.query_one("#detail-title", Static)
        title.update(plain_text(title_text))
        title.set_class(active, "-active")

        self.query_one("#detail-tabs", Static).update(
            plain_text(format_detail_tabs(detail_tab=model.tab, has_response=model.has_response))
        )
        if model.text == self._detail_cache:
            return
        self.query_one("#detail-body", Static).update(plain_text(model.text))
        self.query_one(VerticalScroll).scroll_home(animate=False)
        self._detail_cache = model.text

    def focus_detail(self) -> None:
        self.query_one(VerticalScroll).focus()
