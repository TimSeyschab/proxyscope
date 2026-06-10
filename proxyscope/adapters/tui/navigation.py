from proxyscope.adapters.tui.models import ActivePane, AuxPanelTabModel, DetailTab, MainMode
from proxyscope.adapters.tui.state import RuntimeUIViewState
from proxyscope.application.journal import LoggedExchange


class RuntimeUINavigationService:
    def __init__(self, state: RuntimeUIViewState) -> None:
        self._state = state

    def set_active_pane(self, pane: ActivePane) -> None:
        self._state.active_pane = pane

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
    ) -> None:
        if not entries:
            self._state.request_cursor = 0
            self._state.selected_request_id = None
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
        if not has_entries:
            self._state.switch_to_request_list_mode()

    def clear_requests(self) -> None:
        self._state.reset_request_view()
        self._state.main_mode = "requests"
        self._state.active_pane = "requests"
        self._state.aux_tab_key = "sites"

    def select_detail_tab(self, tab: DetailTab) -> None:
        self._state.detail_tab = tab
        self._state.active_pane = "detail"

    def select_aux_tab(self, tab_key: str) -> None:
        self._state.focus_aux_tab(tab_key)

    def select_aux_item(self, cursor: int) -> None:
        if self._state.aux_tab_key == "sites":
            self._state.site_cursor = cursor
        else:
            self._state.policy_cursor = cursor
        self._state.active_pane = "aux"

    def toggle_aux_visibility(self) -> None:
        self._state.toggle_aux_visibility()

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
        return self._state.aux_visible and self._state.aux_tab_key == "policies"


def focus_step_order(*, main_mode: MainMode, aux_visible: bool, aux_tabs: list[AuxPanelTabModel]) -> list[str]:
    steps = ["requests"]
    if main_mode == "request_detail":
        steps.extend(["detail-request", "detail-response"])
    if aux_visible:
        steps.extend(f"aux-{tab.key}" for tab in aux_tabs)
    steps.append("command")
    return steps


def _clamp_cursor(cursor: int, item_count: int) -> int:
    return min(max(cursor, 0), max(0, item_count - 1))
