from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget

from proxyscope.adapters.tui.components.command_bar import StatusFooter
from proxyscope.adapters.tui.components.contracts import TRAFFIC_COMPONENT_ID, ComponentFocus, ComponentId
from proxyscope.adapters.tui.components.request_detail import RequestDetailPane
from proxyscope.adapters.tui.components.request_list import RequestList
from proxyscope.adapters.tui.models import RuntimeScreenModel

RuntimeContentLayout = Literal["horizontal", "vertical"]


class TrafficViewPane(Horizontal):
    component_id: ComponentId = TRAFFIC_COMPONENT_ID

    def __init__(self) -> None:
        super().__init__(id="traffic-view")

    def compose(self) -> ComposeResult:
        yield RequestList()
        yield RequestDetailPane()

    def render_model(self, model: RuntimeScreenModel) -> None:
        self.query_one(RequestList).render_model(
            model.request_list,
            active=model.active_pane == RequestList.focus_target.pane_key,
        )
        self.query_one(RequestDetailPane).render_model(
            model.detail,
            active=model.active_pane == RequestDetailPane.focus_target(model.detail.tab).pane_key,
        )

    def render_detail(self, model: RuntimeScreenModel) -> None:
        self.query_one(RequestDetailPane).render_model(
            model.detail,
            active=model.active_pane == RequestDetailPane.focus_target(model.detail.tab).pane_key,
        )

    def apply_layout(self, *, content_layout: RuntimeContentLayout, model: RuntimeScreenModel) -> None:
        self.styles.layout = content_layout
        request_list = self.query_one(RequestList)
        detail_pane = self.query_one(RequestDetailPane)
        detail_pane.display = model.detail_visible

        if content_layout == "vertical":
            if not model.detail_visible or model.detail_ratio == "half":
                request_list.styles.height = "1fr"
            else:
                request_list.styles.height = "2fr"
            detail_pane.styles.height = "1fr"
            request_list.styles.width = "1fr"
            detail_pane.styles.width = "1fr"
            return

        request_list.styles.height = "1fr"
        detail_pane.styles.height = "1fr"
        request_list.styles.width = "1fr" if model.detail_ratio == "half" else "2fr"
        detail_pane.styles.width = "1fr"

    def focus_requests(self) -> None:
        self.query_one(RequestList).focus_list()

    def focus_detail(self) -> None:
        self.query_one(RequestDetailPane).focus_detail()

    @staticmethod
    def focus_order(*, detail_visible: bool) -> list[ComponentFocus]:
        if not detail_visible:
            return [RequestList.focus_target]
        return [
            RequestList.focus_target,
            RequestDetailPane.focus_target("request"),
            RequestDetailPane.focus_target("response"),
        ]


class RuntimeViewFrame(Vertical):
    def __init__(self, *content: Widget) -> None:
        super().__init__(id="root")
        self._content = content

    def compose(self) -> ComposeResult:
        with Vertical(id="view-content"):
            yield from self._content
        yield StatusFooter()
