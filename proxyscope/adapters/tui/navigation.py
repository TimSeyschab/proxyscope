from typing import Literal, cast

from proxyscope.adapters.tui.components.contracts import (
    ADMIN_COMPONENT_ID,
    REQUESTS_FOCUS,
    TRAFFIC_COMPONENT_ID,
    ComponentFocus,
    admin_tab_focus,
    detail_focus,
)
from proxyscope.adapters.tui.components.runtime_view import TrafficViewPane
from proxyscope.adapters.tui.components.tabbed_list import TabbedListPane
from proxyscope.adapters.tui.models import DetailTab, RuntimeView, TabbedListTabModel
from proxyscope.adapters.tui.state import RuntimeUIViewState
from proxyscope.application.journal import LoggedExchange


class RuntimeUINavigationService:
    def __init__(self, state: RuntimeUIViewState) -> None:
        self._state = state

    def set_active_focus(self, focus: ComponentFocus) -> None:
        self._state.set_active_focus(focus)

    def switch_view(self, view: RuntimeView) -> None:
        self._state.switch_view(view)

    def select_request(self, entries: list[LoggedExchange], cursor: int) -> None:
        self.sync_request_selection(entries, preferred_cursor=cursor)

    def open_selected_request_detail(self, entries: list[LoggedExchange]) -> bool:
        if not entries:
            return False
        self.sync_request_selection(entries)
        self._state.open_selected_request_detail()
        return True

    def selected_request(self, entries: list[LoggedExchange]) -> LoggedExchange | None:
        if not entries:
            self.sync_request_selection(entries)
            return None
        self.sync_request_selection(entries)
        return entries[self._state.request_cursor]

    def sync_request_selection(
        self,
        entries: list[LoggedExchange],
        *,
        preferred_cursor: int | None = None,
        follow_top: bool = False,
    ) -> None:
        if not entries:
            self._state.request_cursor = 0
            self._state.selected_request_id = None
            return

        if follow_top and preferred_cursor is None:
            self._state.request_cursor = 0
            self._state.selected_request_id = entries[0].request_id
            return

        selected_id = self._state.selected_request_id
        if selected_id is not None and preferred_cursor is None:
            for index, entry in enumerate(entries):
                if entry.request_id == selected_id:
                    self._state.request_cursor = index
                    return

        cursor_source = self._state.request_cursor if preferred_cursor is None else preferred_cursor
        clamped_cursor = min(max(cursor_source, 0), len(entries) - 1)
        self._state.request_cursor = clamped_cursor
        self._state.selected_request_id = entries[clamped_cursor].request_id

    def reset_request_view(self, *, has_entries: bool) -> None:
        self._state.reset_request_view()
        if not has_entries and self._state.active_component_id == TRAFFIC_COMPONENT_ID:
            self._state.set_active_focus(REQUESTS_FOCUS)

    def select_detail_tab(self, tab: DetailTab) -> None:
        self._state.detail_visible = True
        self._state.detail_tab = tab
        self._state.set_active_focus(detail_focus(tab))

    def toggle_detail_ratio(self) -> None:
        self._state.toggle_detail_ratio()

    def select_admin_tab(self, tab_key: Literal["sites", "policies"]) -> None:
        self._state.set_active_focus(admin_tab_focus(tab_key))

    def select_aux_tab(self, tab_key: str) -> None:
        if tab_key in {"sites", "policies"}:
            self.select_admin_tab(cast(Literal["sites", "policies"], tab_key))

    def select_aux_item(self, cursor: int) -> None:
        if self._state.admin_tab_key == "sites":
            self._state.site_cursor = cursor
        else:
            self._state.policy_cursor = cursor
        self._state.set_active_focus(admin_tab_focus(self._state.admin_tab_key))

    def go_back(self) -> bool:
        return self._state.go_back()

    def selected_site(self, sites: list[str]) -> str | None:
        if not sites:
            return None
        self._state.site_cursor = _clamp_cursor(self._state.site_cursor, len(sites))
        return sites[self._state.site_cursor]

    def selected_policy_name(self, policy_names: list[str]) -> str | None:
        if not policy_names:
            return None
        self._state.policy_cursor = _clamp_cursor(self._state.policy_cursor, len(policy_names))
        return policy_names[self._state.policy_cursor]

    def clamp_policy_cursor(self, item_count: int) -> None:
        self._state.policy_cursor = _clamp_cursor(self._state.policy_cursor, item_count)

    def is_policy_tab_active(self) -> bool:
        return self._state.active_component_id == ADMIN_COMPONENT_ID and self._state.admin_tab_key == "policies"


def focus_step_order(
    *,
    active_view: RuntimeView,
    detail_visible: bool,
    admin_tabs: list[TabbedListTabModel],
) -> list[ComponentFocus]:
    if active_view == ADMIN_COMPONENT_ID.value:
        return TabbedListPane.focus_order(admin_tabs)
    return TrafficViewPane.focus_order(detail_visible=detail_visible)


def _clamp_cursor(cursor: int, item_count: int) -> int:
    return min(max(cursor, 0), max(0, item_count - 1))
