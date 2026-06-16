from dataclasses import dataclass
from typing import Literal

RuntimeView = Literal["traffic", "admin"]
ActivePane = Literal["requests", "detail", "sites", "policies"]
DetailTab = Literal["request", "response"]
DetailRatio = Literal["third", "half"]


@dataclass
class RuntimeUIViewState:
    status_message: str = "Press ':' for commands."
    should_exit: bool = False

    site_cursor: int = 0
    policy_cursor: int = 0
    request_cursor: int = 0
    selected_request_id: int | None = None
    request_follow_top: bool = False
    detail_tab: DetailTab = "request"
    detail_visible: bool = False
    detail_ratio: DetailRatio = "third"

    active_view: RuntimeView = "admin"
    active_pane: ActivePane = "sites"
    admin_tab_key: Literal["sites", "policies"] = "sites"

    def reset_request_view(self) -> None:
        self.request_cursor = 0
        self.selected_request_id = None

    def switch_view(self, view: RuntimeView) -> None:
        self.active_view = view
        if view == "admin":
            self.active_pane = self.admin_tab_key
            return
        if self.active_pane == "detail" and not self.detail_visible:
            self.active_pane = "requests"
        elif self.active_pane not in {"requests", "detail"}:
            self.active_pane = "requests"

    def focus_admin_tab(self, tab_key: Literal["sites", "policies"]) -> None:
        self.active_view = "admin"
        self.admin_tab_key = tab_key
        self.active_pane = tab_key

    def open_selected_request_detail(self) -> None:
        self.active_view = "traffic"
        self.detail_visible = True
        self.active_pane = "detail"
        self.detail_tab = "request"

    def toggle_detail_ratio(self) -> None:
        self.detail_ratio = "half" if self.detail_ratio == "third" else "third"

    def go_back(self) -> bool:
        if self.active_view == "traffic" and self.detail_visible:
            self.detail_visible = False
            self.active_pane = "requests"
            return True
        return False
