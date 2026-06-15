from dataclasses import dataclass
from typing import Literal

MainMode = Literal["requests", "request_detail"]
ActivePane = Literal["requests", "detail", "aux"]
DetailTab = Literal["request", "response"]


@dataclass
class RuntimeUIViewState:
    status_message: str = "Type 'help' for commands."
    should_exit: bool = False

    site_cursor: int = 0
    policy_cursor: int = 0
    request_cursor: int = 0
    selected_request_id: int | None = None
    request_follow_top: bool = False
    detail_tab: DetailTab = "request"

    main_mode: MainMode = "requests"
    active_pane: ActivePane = "requests"
    aux_visible: bool = True
    aux_tab_key: str = "sites"

    def reset_request_view(self) -> None:
        self.request_cursor = 0
        self.selected_request_id = None

    def switch_to_request_list_mode(self) -> None:
        self.main_mode = "requests"
        self.detail_tab = "request"
        if self.active_pane == "detail":
            self.active_pane = "requests"

    def focus_aux_tab(self, tab_key: str) -> None:
        self.aux_visible = True
        self.aux_tab_key = tab_key
        self.active_pane = "aux"

    def toggle_aux_visibility(self) -> None:
        self.aux_visible = not self.aux_visible
        if not self.aux_visible and self.active_pane == "aux":
            self.active_pane = "requests"

    def open_selected_request_detail(self) -> None:
        self.main_mode = "request_detail"
        self.active_pane = "detail"
        self.detail_tab = "request"

    def go_back(self) -> bool:
        if self.aux_visible:
            self.aux_visible = False
            if self.active_pane == "aux":
                self.active_pane = "detail" if self.main_mode == "request_detail" else "requests"
            return True
        if self.main_mode == "request_detail":
            self.switch_to_request_list_mode()
            return True
        return False
