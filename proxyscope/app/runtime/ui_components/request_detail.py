from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from proxyscope.app.runtime.ui_components.rendering import format_detail_tabs, plain_text
from proxyscope.app.runtime.ui_models import MainMode, RequestDetailModel


class RequestDetailPane(Vertical):
    def __init__(self) -> None:
        super().__init__(id="detail-pane", classes="pane")
        self._detail_cache = ""

    def compose(self) -> ComposeResult:
        yield Static(id="detail-title", classes="pane-title")
        yield Static(id="detail-tabs")
        with VerticalScroll(id="detail-scroll", can_focus=True):
            yield Static(id="detail-body")

    def render_model(self, model: RequestDetailModel, *, main_mode: MainMode, active: bool) -> None:
        title_text = "DETAIL" if main_mode != "request_detail" else f"DETAIL [{model.tab}]"
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
