from dataclasses import dataclass, field
from typing import Literal

from proxyscope.adapters.tui.components.contracts import (
    ADMIN_COMPONENT_ID,
    REQUESTS_FOCUS,
    TRAFFIC_COMPONENT_ID,
    ComponentFocus,
    ComponentId,
    FocusTargetId,
    admin_tab_focus,
    detail_focus,
)

RuntimeView = str
ActivePane = str
DetailTab = Literal["request", "response"]
DetailRatio = Literal["third", "half"]


@dataclass
class RuntimeComponentState:
    active_focus: ComponentFocus


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

    active_component_id: ComponentId = ADMIN_COMPONENT_ID
    component_states: dict[ComponentId, RuntimeComponentState] = field(
        default_factory=lambda: _default_component_states()
    )

    @property
    def active_focus(self) -> ComponentFocus:
        return self.component_states[self.active_component_id].active_focus

    @property
    def active_view(self) -> str:
        return self.active_component_id.value

    @property
    def active_pane(self) -> ActivePane:
        return self.active_focus.pane_key

    @property
    def admin_tab_key(self) -> str:
        return self.component_states[ADMIN_COMPONENT_ID].active_focus.pane_key

    def reset_request_view(self) -> None:
        self.request_cursor = 0
        self.selected_request_id = None

    def switch_view(self, view: RuntimeView) -> None:
        component_id = ComponentId(view)
        if component_id == ADMIN_COMPONENT_ID:
            self.active_component_id = ADMIN_COMPONENT_ID
            return
        if component_id != TRAFFIC_COMPONENT_ID:
            self.active_component_id = component_id
            self.component_states.setdefault(
                component_id,
                RuntimeComponentState(ComponentFocus(component_id, FocusTargetId(view), view)),
            )
            return

        self.active_component_id = TRAFFIC_COMPONENT_ID
        if self.active_focus.pane_key == detail_focus(self.detail_tab).pane_key and not self.detail_visible:
            self.set_active_focus(REQUESTS_FOCUS)
        elif self.active_focus.component_id != TRAFFIC_COMPONENT_ID:
            self.set_active_focus(REQUESTS_FOCUS)

    def set_active_focus(self, focus: ComponentFocus) -> None:
        self.component_states[focus.component_id] = RuntimeComponentState(focus)
        self.active_component_id = focus.component_id

    def open_selected_request_detail(self) -> None:
        self.detail_visible = True
        self.detail_tab = "request"
        self.set_active_focus(detail_focus(self.detail_tab))

    def toggle_detail_ratio(self) -> None:
        self.detail_ratio = "half" if self.detail_ratio == "third" else "third"

    def go_back(self) -> bool:
        if self.active_component_id == TRAFFIC_COMPONENT_ID and self.detail_visible:
            self.detail_visible = False
            self.set_active_focus(REQUESTS_FOCUS)
            return True
        return False


def _default_component_states() -> dict[ComponentId, RuntimeComponentState]:
    return {
        TRAFFIC_COMPONENT_ID: RuntimeComponentState(REQUESTS_FOCUS),
        ADMIN_COMPONENT_ID: RuntimeComponentState(admin_tab_focus("sites")),
    }
