from dataclasses import dataclass
from typing import Callable, Literal

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, OptionList, Static

from proxyscope.app.runtime.cli import RuntimeCLI
from proxyscope.app.runtime.journal import LoggedExchange
from proxyscope.app.runtime.ui_models import AuxPanelTabModel, RuntimeScreenModel

RuntimeContentLayout = Literal["horizontal", "vertical"]


@dataclass(frozen=True)
class RuntimeLayoutPlan:
    content_layout: RuntimeContentLayout
    show_detail: bool
    show_sidebar: bool


class HelpModal(ModalScreen[None]):
    CSS = """
    HelpModal {
        align: center middle;
    }

    #help-dialog {
        width: 92;
        max-width: 90%;
        max-height: 85%;
        background: #10171e;
        border: round #8fd3ff;
        padding: 1 2;
    }

    #help-title {
        color: #8fd3ff;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #help-body {
        color: #e6edf3;
        padding: 0;
    }

    #help-footer {
        color: #91a7bb;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("enter", "close", "Close", show=False),
    ]

    def __init__(self, help_text: str) -> None:
        super().__init__()
        self._help_text = help_text

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static(_plain_text("HELP"), id="help-title")
            yield Static(_plain_text(self._help_text), id="help-body")
            yield Static(_plain_text("Esc or Enter closes this dialog."), id="help-footer")

    def action_close(self) -> None:
        self.dismiss()


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


class RuntimeTextualApp(App[None]):
    CSS = """
    Screen {
        background: #11161c;
        color: #e6edf3;
    }

    #root {
        layout: vertical;
        height: 100%;
        padding: 0;
        margin: 0;
    }

    #content {
        layout: horizontal;
        height: 1fr;
        padding: 0;
        margin: 0;
    }

    .pane {
        border: round #4b647a;
        background: #16202a;
        padding: 0;
        margin: 0;
    }

    .pane-title {
        color: #8fd3ff;
        text-style: bold;
        padding: 0 1;
        margin: 0;
    }

    .pane-title.-active {
        color: #ffd280;
    }

    #detail-tabs {
        color: #91a7bb;
        padding: 0 1;
        margin: 0;
        border-bottom: solid #31424f;
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
        border: solid #31424f;
    }

    #detail-body {
        padding: 0;
        margin: 0;
    }

    #sidebar-list {
        height: 1fr;
        background: #10171e;
        border: solid #31424f;
    }

    #sidebar-tabs {
        color: #91a7bb;
        padding: 0 1;
        margin: 0;
        border-bottom: solid #31424f;
    }

    #command-pane {
        height: 4;
        border-top: solid #31424f;
        padding: 0;
        margin: 0;
        background: #0d1318;
    }

    #command-input {
        margin: 0;
        padding: 0 1;
        border: none;
        background: #0d1318;
    }

    #status-line {
        color: #ffd280;
        text-style: bold;
        padding: 0 1;
        margin: 0;
    }

    #config-line {
        color: #91a7bb;
        padding: 0 1;
        margin: 0;
    }
    """

    BINDINGS = [
        Binding("shift+b", "go_back", "Back", show=True, priority=True),
        Binding("shift+s", "toggle_sites_sidebar", "Sidebar", show=True, priority=True),
        Binding("shift+p", "show_policies", "Policies", show=True, priority=True),
        Binding("shift+a", "add_site_to_whitelist", "Whitelist", show=False, priority=True),
        Binding("shift+u", "remove_site_from_whitelist", "Unwhitelist", show=False, priority=True),
        Binding("shift+d", "disable_policy", "Disable", show=False, priority=True),
        Binding("shift+e", "enable_policy", "Enable", show=False, priority=True),
        Binding("shift+i", "edit_policy", "Edit Policy", show=False, priority=True),
        Binding("shift+m", "add_editor_policy", "Editor Rule", show=False, priority=True),
        Binding("shift+r", "replay_request", "Replay", show=False, priority=True),
        Binding("shift+x", "remove_policy", "Delete Policy", show=False, priority=True),
    ]

    def __init__(self, controller: RuntimeCLI) -> None:
        super().__init__()
        self._controller = controller
        self._request_rows: tuple[tuple[str, str, str, str, str, str], ...] = ()
        self._sidebar_items: tuple[str, ...] = ()
        self._sidebar_key: str | None = None
        self._detail_cache = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            with Horizontal(id="content"):
                with Vertical(id="main-pane", classes="pane"):
                    yield Static(id="main-title", classes="pane-title")
                    yield DataTable(id="requests")
                with Vertical(id="detail-pane", classes="pane"):
                    yield Static(id="detail-title", classes="pane-title")
                    yield Static(id="detail-tabs")
                    with VerticalScroll(id="detail-scroll", can_focus=True):
                        yield Static(id="detail-body")
                with Vertical(id="sidebar-pane", classes="pane"):
                    yield Static(id="sidebar-title", classes="pane-title")
                    yield Static(id="sidebar-tabs")
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
        self.set_interval(0.2, self._tick)
        table.focus()
        self._controller._active_pane = "requests"
        self._refresh_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        event.input.value = ""
        if not command:
            return
        if self._controller.is_help_command(command):
            self._controller.execute_command(command)
            self._refresh_screen()
            self.push_screen(HelpModal(self._controller.build_help_text()))
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

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        widget = event.widget
        if widget.id == "requests":
            self._controller._active_pane = "requests"
        elif widget.id == "detail-scroll":
            self._controller._active_pane = "detail"
        elif widget.id == "sidebar-list":
            self._controller._active_pane = "aux"

    def on_key(self, event: events.Key) -> None:
        if self._handle_shift_shortcut_key(event):
            return
        if event.key not in {"tab", "shift+tab"}:
            return
        event.stop()
        event.prevent_default()
        self._cycle_focus(backward=event.key == "shift+tab")

    def _handle_shift_shortcut_key(self, event: events.Key) -> bool:
        focused = self.focused
        if focused is not None and focused.id == "command-input":
            return False

        shortcut = _shortcut_token_from_key_event(key=event.key, character=event.character)
        if shortcut is None:
            return False

        shortcuts: dict[str, Callable[[], None]] = {
            "a": self.action_add_site_to_whitelist,
            "b": self.action_go_back,
            "d": self.action_disable_policy,
            "e": self.action_enable_policy,
            "i": self.action_edit_policy,
            "m": self.action_add_editor_policy,
            "p": self.action_show_policies,
            "r": self.action_replay_request,
            "s": self.action_toggle_sites_sidebar,
            "u": self.action_remove_site_from_whitelist,
            "x": self.action_remove_policy,
        }
        action = shortcuts.get(shortcut)
        if action is None:
            return False
        event.stop()
        event.prevent_default()
        action()
        return True

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
            self._controller._view_state.site_cursor = event.option_index
        else:
            self._controller._view_state.policy_cursor = event.option_index

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.on_option_list_option_highlighted(event)
        if self._controller._aux_tab_key != "policies":
            return
        self._controller._edit_selected_policy(suspend_ui=self.suspend)
        self._refresh_screen()

    def action_go_back(self) -> None:
        self._controller._go_back()
        self._sync_focus_after_navigation()
        self._refresh_screen()

    def action_toggle_sites_sidebar(self) -> None:
        if self._controller._view_state.aux_visible and self._controller._aux_tab_key == "sites":
            self._controller._toggle_aux_visibility()
            self._sync_focus_after_navigation()
            self._refresh_screen()
            return
        self._controller._focus_aux_tab("sites")
        self.query_one("#sidebar-list", OptionList).focus()
        self._refresh_screen()

    def action_show_policies(self) -> None:
        self._controller._focus_aux_tab("policies")
        self.query_one("#sidebar-list", OptionList).focus()
        self._refresh_screen()

    def action_add_site_to_whitelist(self) -> None:
        self._controller._add_selected_site_to_whitelist()
        self._refresh_screen()

    def action_remove_site_from_whitelist(self) -> None:
        self._controller._remove_selected_site_from_whitelist()
        self._refresh_screen()

    def action_disable_policy(self) -> None:
        self._controller._disable_selected_policy()
        self._refresh_screen()

    def action_enable_policy(self) -> None:
        self._controller._enable_selected_policy()
        self._refresh_screen()

    def action_edit_policy(self) -> None:
        self._controller._edit_selected_policy(suspend_ui=self.suspend)
        self._refresh_screen()

    def action_add_editor_policy(self) -> None:
        self._controller._add_selected_request_to_editor_policy(suspend_ui=self.suspend)
        self._refresh_screen()

    def action_replay_request(self) -> None:
        self._controller._edit_and_resend_selected_request_with_ui_suspend(suspend_ui=self.suspend)
        self._refresh_screen()

    def action_remove_policy(self) -> None:
        self._controller._remove_selected_policy()
        self._refresh_screen()

    def _tick(self) -> None:
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
        self._render_detail_tabs(model)
        self._render_sidebar(model)
        self._render_sidebar_tabs(model)
        self.query_one("#status-line", Static).update(_plain_text(model.status_message))
        self.query_one("#config-line", Static).update(_plain_text(model.config_text))
        if self._controller._view_state.should_exit:
            self.exit()

    def _refresh_detail_only(self) -> None:
        model = self._controller.build_screen_model()
        self._render_detail(model)
        self._render_detail_tabs(model)

    def _render_titles(self, model: RuntimeScreenModel) -> None:
        self._update_title("#main-title", model.request_title, active=model.active_pane == "requests")
        detail_title = "DETAIL"
        if model.main_mode == "request_detail":
            detail_title = f"DETAIL [{model.detail_tab}]"
        self._update_title("#detail-title", detail_title, active=model.active_pane == "detail")
        self._update_title("#sidebar-title", "SIDEBAR", active=model.active_pane == "aux")

    def _update_title(self, selector: str, text: str, *, active: bool) -> None:
        widget = self.query_one(selector, Static)
        widget.update(_plain_text(text))
        if active:
            widget.add_class("-active")
        else:
            widget.remove_class("-active")

    def _render_requests(self, model: RuntimeScreenModel) -> None:
        table = self.query_one("#requests", DataTable)
        request_rows = _request_rows_signature(model.request_entries)
        if request_rows != self._request_rows:
            table.clear(columns=False)
            for row in request_rows:
                table.add_row(*row)
            self._request_rows = request_rows
        if model.request_entries:
            target_row = min(model.request_cursor, len(model.request_entries) - 1)
            table.move_cursor(row=target_row, animate=False, scroll=True)

    def _render_detail(self, model: RuntimeScreenModel) -> None:
        entry = model.request_entries[model.request_cursor] if model.request_entries else None
        detail_text = _detail_signature(entry, model.detail_tab)
        if detail_text == self._detail_cache:
            return
        self.query_one("#detail-body", Static).update(_plain_text(detail_text))
        self.query_one("#detail-scroll", VerticalScroll).scroll_home(animate=False)
        self._detail_cache = detail_text

    def _render_detail_tabs(self, model: RuntimeScreenModel) -> None:
        entry = model.request_entries[model.request_cursor] if model.request_entries else None
        self.query_one("#detail-tabs", Static).update(
            _plain_text(
                _format_detail_tabs(detail_tab=model.detail_tab, has_response=entry is not None and entry.response is not None)
            )
        )

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

    def _render_sidebar_tabs(self, model: RuntimeScreenModel) -> None:
        self.query_one("#sidebar-tabs", Static).update(
            _plain_text(_format_sidebar_tabs(aux_tabs=model.aux_tabs, active_key=model.aux_active_key))
        )

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

    def _cycle_focus(self, *, backward: bool) -> None:
        steps = self._focus_steps()
        current = self._current_focus_step()
        if current not in steps:
            current = "requests"
        index = steps.index(current)
        offset = -1 if backward else 1
        self._focus_step(steps[(index + offset) % len(steps)])

    def _focus_steps(self) -> list[str]:
        return _focus_step_order(
            main_mode=self._controller._view_state.main_mode,
            aux_visible=self._controller._view_state.aux_visible,
            aux_tabs=self._controller.build_screen_model().aux_tabs,
        )

    def _current_focus_step(self) -> str:
        focused = self.focused
        if focused is None:
            return "requests"
        if focused.id == "detail-scroll":
            return f"detail-{self._controller._view_state.detail_tab}"
        if focused.id == "sidebar-list":
            return f"aux-{self._controller._view_state.aux_tab_key}"
        if focused.id == "command-input":
            return "command"
        return "requests"

    def _focus_step(self, step: str) -> None:
        if step == "requests":
            self.query_one("#requests", DataTable).focus()
            self._controller._active_pane = "requests"
            return
        if step == "detail-request":
            self._controller._view_state.detail_tab = "request"
            self.query_one("#detail-scroll", VerticalScroll).focus()
            self._controller._active_pane = "detail"
            self._refresh_screen()
            return
        if step == "detail-response":
            self._controller._view_state.detail_tab = "response"
            self.query_one("#detail-scroll", VerticalScroll).focus()
            self._controller._active_pane = "detail"
            self._refresh_screen()
            return
        if step.startswith("aux-"):
            tab_key = step.removeprefix("aux-")
            self._controller._focus_aux_tab(tab_key)
            self.query_one("#sidebar-list", OptionList).focus()
            self._controller._active_pane = "aux"
            self._refresh_screen()
            return
        self.query_one("#command-input", Input).focus()


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


def _request_rows_signature(entries: list[LoggedExchange]) -> tuple[tuple[str, str, str, str, str, str], ...]:
    return tuple(_request_row(entry) for entry in entries)


def _format_detail(entry: LoggedExchange | None, detail_tab: str) -> str:
    if entry is None:
        return "No request selected."
    if detail_tab == "response":
        return _format_response_detail(entry)
    return _format_request_detail(entry)


def _detail_signature(entry: LoggedExchange | None, detail_tab: str) -> str:
    return _format_detail(entry, detail_tab)


def _plain_text(value: str) -> Text:
    return Text(value, no_wrap=False, overflow="fold")


def _shortcut_token_from_key_event(*, key: str, character: str | None) -> str | None:
    known = {"a", "b", "d", "e", "i", "m", "p", "r", "s", "u", "x"}
    normalized_key = key.lower()
    if normalized_key.startswith("shift+"):
        candidate = normalized_key.removeprefix("shift+")
        return candidate if candidate in known else None
    if len(key) == 1 and key.isalpha() and key.isupper():
        candidate = key.lower()
        return candidate if candidate in known else None
    if character and len(character) == 1 and character.isalpha() and character.isupper():
        candidate = character.lower()
        return candidate if candidate in known else None
    return None


def _focus_step_order(*, main_mode: str, aux_visible: bool, aux_tabs: list[AuxPanelTabModel]) -> list[str]:
    steps = ["requests"]
    if main_mode == "request_detail":
        steps.extend(["detail-request", "detail-response"])
    if aux_visible:
        steps.extend(f"aux-{tab.key}" for tab in aux_tabs)
    steps.append("command")
    return steps


def _format_detail_tabs(*, detail_tab: str, has_response: bool) -> str:
    request_label = "[Request]" if detail_tab == "request" else " Request "
    response_suffix = "" if has_response else " (pending)"
    response_label = f"[Response{response_suffix}]" if detail_tab == "response" else f" Response{response_suffix} "
    return f"{request_label} | {response_label}"


def _format_sidebar_tabs(*, aux_tabs: list[AuxPanelTabModel], active_key: str) -> str:
    labels: list[str] = []
    for tab in aux_tabs:
        label = tab.title.split(":", 1)[-1].title()
        labels.append(f"[{label}]" if tab.key == active_key else f" {label} ")
    return " | ".join(labels) if labels else ""


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
