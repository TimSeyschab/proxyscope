from dataclasses import dataclass
from typing import Callable, Literal

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Input, OptionList, Static

from proxyscope.app.runtime.cli import RuntimeCLI
from proxyscope.app.runtime.journal import LoggedExchange
from proxyscope.app.runtime.tui import RuntimeScreenModel

RuntimeContentLayout = Literal["horizontal", "vertical"]


@dataclass(frozen=True)
class RuntimeLayoutPlan:
    content_layout: RuntimeContentLayout
    show_detail: bool
    show_sidebar: bool


def determine_runtime_layout(*, width: int, model: RuntimeScreenModel) -> RuntimeLayoutPlan:
    show_detail = model.main_mode == "request_detail"
    show_sidebar = model.aux_visible
    content_layout: RuntimeContentLayout = "horizontal"

    if width < 100:
        content_layout = "vertical"

    if width < 140 and show_detail and show_sidebar:
        if model.active_pane == "aux":
            show_detail = False
        else:
            show_sidebar = False

    return RuntimeLayoutPlan(
        content_layout=content_layout,
        show_detail=show_detail,
        show_sidebar=show_sidebar,
    )


class RuntimeTextualUI(RuntimeCLI):
    def run(
        self,
        *,
        shutdown_server: Callable[[], None],
        on_cache_toggle: Callable[[], None] | None = None,
    ) -> None:
        self._shutdown_server = shutdown_server
        self._on_cache_toggle = on_cache_toggle
        app = _RuntimeTextualApp(self)
        app.run()


class _RuntimeTextualApp(App[None]):
    CSS = """
    Screen {
        background: #11161c;
        color: #e6edf3;
    }

    #root {
        layout: vertical;
        height: 100%;
    }

    #content {
        layout: horizontal;
        height: 1fr;
    }

    .pane {
        border: round #4b647a;
        background: #16202a;
        padding: 0 1;
    }

    .pane-title {
        color: #8fd3ff;
        text-style: bold;
        margin: 0 0 1 0;
    }

    .pane-title.-active {
        color: #ffd280;
    }

    #main-pane {
        width: 2fr;
        min-width: 36;
    }

    #detail-pane {
        width: 1fr;
        min-width: 30;
    }

    #sidebar-pane {
        width: 32;
        min-width: 24;
    }

    #requests {
        height: 1fr;
    }

    #detail-scroll {
        height: 1fr;
        background: #10171e;
        border: tall #31424f;
    }

    #detail-body {
        padding: 0 1;
    }

    #sidebar-list {
        height: 1fr;
        background: #10171e;
        border: tall #31424f;
    }

    #command-pane {
        height: 5;
        border-top: solid #31424f;
        padding: 0 1;
        background: #0d1318;
    }

    #command-input {
        margin: 0 0 1 0;
    }

    #status-line {
        color: #ffd280;
        text-style: bold;
    }

    #config-line {
        color: #91a7bb;
    }
    """

    BINDINGS = [
        Binding("shift+b", "go_back", "Back", show=True),
        Binding("shift+s", "show_sites", "Sites", show=True),
        Binding("shift+p", "show_policies", "Policies", show=True),
        Binding("shift+v", "toggle_sidebar", "Sidebar", show=True),
        Binding("shift+t", "toggle_detail_tab", "Detail Tab", show=True),
        Binding("shift+a", "add_site_to_whitelist", "Whitelist", show=False),
        Binding("shift+d", "remove_or_disable", "Remove", show=False),
        Binding("shift+e", "enable_policy", "Enable", show=False),
        Binding("shift+i", "edit_policy", "Edit Policy", show=False),
        Binding("shift+m", "add_editor_policy", "Editor Rule", show=False),
        Binding("shift+r", "replay_request", "Replay", show=False),
        Binding("shift+x", "remove_policy", "Delete Policy", show=False),
    ]

    def __init__(self, controller: RuntimeCLI) -> None:
        super().__init__()
        self._controller = controller
        self._request_ids: tuple[int, ...] = ()
        self._sidebar_items: tuple[str, ...] = ()
        self._sidebar_key: str | None = None
        self._detail_cache: tuple[int | None, str] = (None, "")

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            with Horizontal(id="content"):
                with Vertical(id="main-pane", classes="pane"):
                    yield Static(id="main-title", classes="pane-title")
                    yield DataTable(id="requests")
                with Vertical(id="detail-pane", classes="pane"):
                    yield Static(id="detail-title", classes="pane-title")
                    with VerticalScroll(id="detail-scroll", can_focus=True):
                        yield Static(id="detail-body")
                with Vertical(id="sidebar-pane", classes="pane"):
                    yield Static(id="sidebar-title", classes="pane-title")
                    yield OptionList(id="sidebar-list")
            with Vertical(id="command-pane"):
                yield Input(placeholder="Type a command and press Enter", id="command-input")
                yield Static(id="status-line")
                yield Static(id="config-line")

    def on_mount(self) -> None:
        table = self.query_one("#requests", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("ID", "Status", "Method", "Host", "Path", "Duration")
        self.set_interval(0.2, self._refresh_screen)
        self.set_interval(0.2, self._poll_pending_actions)
        table.focus()
        self._controller._active_pane = "requests"
        self._refresh_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        event.input.value = ""
        if not command:
            return
        self._controller.execute_command(command)
        if self._controller._view_state.should_exit:
            self.exit()
            return
        self._refresh_screen()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._controller._active_pane = "requests"
        self._controller._view_state.request_cursor = event.cursor_row
        self._refresh_detail_only()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._controller._active_pane = "requests"
        self._controller._view_state.request_cursor = event.cursor_row
        self._controller._open_selected_request_detail()
        self.query_one("#detail-scroll", VerticalScroll).focus()
        self._controller._active_pane = "detail"
        self._refresh_screen()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._controller._active_pane = "aux"
        if self._controller._aux_tab_key == "sites":
            self._controller._view_state.site_cursor = event.index
        else:
            self._controller._view_state.policy_cursor = event.index

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.on_option_list_option_highlighted(event)

    def action_go_back(self) -> None:
        self._controller._go_back()
        self._sync_focus_after_navigation()
        self._refresh_screen()

    def action_show_sites(self) -> None:
        self._controller._focus_aux_tab("sites")
        self.query_one("#sidebar-list", OptionList).focus()
        self._refresh_screen()

    def action_show_policies(self) -> None:
        self._controller._focus_aux_tab("policies")
        self.query_one("#sidebar-list", OptionList).focus()
        self._refresh_screen()

    def action_toggle_sidebar(self) -> None:
        self._controller._toggle_aux_visibility()
        self._sync_focus_after_navigation()
        self._refresh_screen()

    def action_toggle_detail_tab(self) -> None:
        if self._controller._view_state.main_mode != "request_detail":
            return
        self._controller._toggle_detail_tab()
        self.query_one("#detail-scroll", VerticalScroll).focus()
        self._controller._active_pane = "detail"
        self._refresh_screen()

    def action_add_site_to_whitelist(self) -> None:
        self._controller._add_selected_site_to_whitelist()
        self._refresh_screen()

    def action_remove_or_disable(self) -> None:
        if self._controller._active_pane == "aux" and self._controller._aux_tab_key == "sites":
            self._controller._remove_selected_site_from_whitelist()
        elif self._controller._active_pane == "aux" and self._controller._aux_tab_key == "policies":
            self._controller._disable_selected_policy()
        self._refresh_screen()

    def action_enable_policy(self) -> None:
        self._controller._enable_selected_policy()
        self._refresh_screen()

    def action_edit_policy(self) -> None:
        self._controller._edit_selected_policy(suspend_ui=self.suspend)
        self._refresh_screen()

    def action_add_editor_policy(self) -> None:
        self._controller._add_selected_request_to_modify_whitelist()
        self._refresh_screen()

    def action_replay_request(self) -> None:
        self._controller._edit_and_resend_selected_request_with_ui_suspend(suspend_ui=self.suspend)
        self._refresh_screen()

    def action_remove_policy(self) -> None:
        self._controller._remove_selected_policy()
        self._refresh_screen()

    def _poll_pending_actions(self) -> None:
        self._controller._process_pending_policy_edit(suspend_ui=self.suspend)
        self._controller._process_pending_editor(suspend_ui=self.suspend)
        if self._controller._view_state.should_exit:
            self.exit()
            return
        self._refresh_screen()

    def _refresh_screen(self) -> None:
        model = self._controller.build_screen_model()
        self._apply_layout(model)
        self._render_titles(model)
        self._render_requests(model)
        self._render_detail(model)
        self._render_sidebar(model)
        self.query_one("#status-line", Static).update(model.status_message)
        self.query_one("#config-line", Static).update(model.config_text)
        if self._controller._view_state.should_exit:
            self.exit()

    def _refresh_detail_only(self) -> None:
        self._render_detail(self._controller.build_screen_model())

    def _render_titles(self, model: RuntimeScreenModel) -> None:
        self._update_title("#main-title", model.request_title, active=model.active_pane == "requests")
        detail_title = "DETAIL"
        if model.main_mode == "request_detail":
            detail_title = f"DETAIL [{model.detail_tab}]"
        self._update_title("#detail-title", detail_title, active=model.active_pane == "detail")
        sidebar_title = "SIDEBAR"
        if model.aux_tabs:
            active_tab = next((tab for tab in model.aux_tabs if tab.key == model.aux_active_key), None)
            if active_tab is not None:
                sidebar_title = active_tab.title
        self._update_title("#sidebar-title", sidebar_title, active=model.active_pane == "aux")

    def _update_title(self, selector: str, text: str, *, active: bool) -> None:
        widget = self.query_one(selector, Static)
        widget.update(text)
        if active:
            widget.add_class("-active")
        else:
            widget.remove_class("-active")

    def _render_requests(self, model: RuntimeScreenModel) -> None:
        table = self.query_one("#requests", DataTable)
        request_ids = tuple(entry.request_id for entry in model.request_entries)
        if request_ids != self._request_ids:
            table.clear(columns=False)
            for entry in model.request_entries:
                table.add_row(*_request_row(entry))
            self._request_ids = request_ids
        if model.request_entries:
            target_row = min(model.request_cursor, len(model.request_entries) - 1)
            table.move_cursor(row=target_row, animate=False, scroll=True)

    def _render_detail(self, model: RuntimeScreenModel) -> None:
        entry = model.request_entries[model.request_cursor] if model.request_entries else None
        detail_text = _format_detail(entry, model.detail_tab)
        cache_key = (entry.request_id if entry is not None else None, model.detail_tab)
        if cache_key == self._detail_cache:
            return
        self.query_one("#detail-body", Static).update(detail_text)
        self.query_one("#detail-scroll", VerticalScroll).scroll_home(animate=False)
        self._detail_cache = cache_key

    def _render_sidebar(self, model: RuntimeScreenModel) -> None:
        option_list = self.query_one("#sidebar-list", OptionList)
        active_tab = next((tab for tab in model.aux_tabs if tab.key == model.aux_active_key), None)
        items = tuple(active_tab.items if active_tab is not None and active_tab.items else (active_tab.empty_label if active_tab else "<empty>",))
        if items != self._sidebar_items or model.aux_active_key != self._sidebar_key:
            option_list.clear_options()
            option_list.add_options(items)
            self._sidebar_items = items
            self._sidebar_key = model.aux_active_key
        if active_tab is None or not active_tab.items:
            option_list.highlighted = 0
            return
        option_list.highlighted = min(active_tab.cursor, len(active_tab.items) - 1)

    def _apply_layout(self, model: RuntimeScreenModel) -> None:
        plan = determine_runtime_layout(width=self.size.width, model=model)
        content = self.query_one("#content", Horizontal)
        content.styles.layout = plan.content_layout
        main_pane = self.query_one("#main-pane", Vertical)
        detail_pane = self.query_one("#detail-pane", Vertical)
        sidebar_pane = self.query_one("#sidebar-pane", Vertical)

        detail_pane.display = plan.show_detail
        sidebar_pane.display = plan.show_sidebar

        if plan.content_layout == "vertical":
            main_pane.styles.height = "2fr"
            detail_pane.styles.height = "1fr"
            sidebar_pane.styles.height = "1fr"
            main_pane.styles.width = "1fr"
            detail_pane.styles.width = "1fr"
            sidebar_pane.styles.width = "1fr"
        else:
            main_pane.styles.height = "1fr"
            detail_pane.styles.height = "1fr"
            sidebar_pane.styles.height = "1fr"
            main_pane.styles.width = "2fr"
            detail_pane.styles.width = "1fr"
            sidebar_pane.styles.width = 32

    def _sync_focus_after_navigation(self) -> None:
        if self._controller._view_state.active_pane == "aux" and self._controller._view_state.aux_visible:
            self.query_one("#sidebar-list", OptionList).focus()
            return
        if self._controller._view_state.main_mode == "request_detail":
            self.query_one("#detail-scroll", VerticalScroll).focus()
            self._controller._active_pane = "detail"
            return
        self.query_one("#requests", DataTable).focus()
        self._controller._active_pane = "requests"


def _request_row(entry: LoggedExchange) -> tuple[str, str, str, str, str, str]:
    status = "---" if entry.response is None else str(entry.response.status_code)
    host = entry.target_host or "-"
    duration = "-" if entry.duration_ms is None else f"{entry.duration_ms:.1f}ms"
    return (
        str(entry.request_id),
        status,
        entry.request.method,
        host,
        entry.request.path,
        duration,
    )


def _format_detail(entry: LoggedExchange | None, detail_tab: str) -> str:
    if entry is None:
        return "No request selected."
    if detail_tab == "response":
        return _format_response_detail(entry)
    return _format_request_detail(entry)


def _format_request_detail(entry: LoggedExchange) -> str:
    header_lines = "\n".join(f"{name}: {value}" for name, value in entry.request.headers) or "<none>"
    body = entry.request.body_preview or "<empty>"
    return (
        f"{entry.request.start_line}\n"
        f"host: {entry.target_host or '-'}\n"
        f"port: {entry.target_port if entry.target_port is not None else '-'}\n"
        f"protocol: {entry.protocol}\n"
        f"client: {entry.client_ip}\n\n"
        f"headers\n"
        f"{header_lines}\n\n"
        f"body\n"
        f"{body}"
    )


def _format_response_detail(entry: LoggedExchange) -> str:
    if entry.response is None:
        return "No response captured."
    header_lines = "\n".join(f"{name}: {value}" for name, value in entry.response.headers) or "<none>"
    body = entry.response.body_preview or "<empty>"
    size = "-" if entry.response.body_size is None else str(entry.response.body_size)
    duration = "-" if entry.duration_ms is None else f"{entry.duration_ms:.1f}ms"
    return (
        f"{entry.response.start_line}\n"
        f"status: {entry.response.status_code} {entry.response.reason}\n"
        f"duration: {duration}\n"
        f"size: {size}\n\n"
        f"headers\n"
        f"{header_lines}\n\n"
        f"body\n"
        f"{body}"
    )
