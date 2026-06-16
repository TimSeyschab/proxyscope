from dataclasses import dataclass
from typing import Callable, Literal, cast

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from proxyscope.adapters.tui.components import (
    CommandModal,
    RequestDetailPane,
    RequestList,
    RuntimeViewFrame,
    StatusFooter,
    TabbedListPane,
)
from proxyscope.adapters.tui.components.rendering import (
    plain_text as _plain_text,
)
from proxyscope.adapters.tui.models import ActivePane, RuntimeScreenModel
from proxyscope.adapters.tui.navigation import focus_step_order as _focus_step_order
from proxyscope.adapters.tui.ui_controller import RuntimeUIController

RuntimeContentLayout = Literal["horizontal", "vertical"]


@dataclass(frozen=True)
class RuntimeLayoutPlan:
    content_layout: RuntimeContentLayout


class HelpModal(ModalScreen[None]):
    CSS = """
    HelpModal {
        align: center middle;
    }

    #help-dialog {
        width: 92;
        max-width: 90%;
        max-height: 85%;
        background: #11161a;
        border: round #d9a94f;
        padding: 1 2;
    }

    #help-title {
        color: #d9a94f;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #help-body {
        color: #e7e1d5;
        padding: 0;
    }

    #help-footer {
        color: #a8ada7;
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
    content_layout: RuntimeContentLayout = "horizontal"

    if width < 100:
        content_layout = "vertical"

    return RuntimeLayoutPlan(content_layout=content_layout)


class RuntimeTextualApp(App[None]):
    CSS_PATH = "runtime.tcss"

    BINDINGS = [
        Binding("shift+1", "show_traffic_view", "Requests", show=True, priority=True),
        Binding("shift+2", "show_admin_view", "Sites/Policies", show=True, priority=True),
        Binding("shift+b", "go_back", "Back", show=True, priority=True),
        Binding("shift+s", "show_sites", "Sites", show=True, priority=True),
        Binding("shift+p", "show_policies", "Policies", show=True, priority=True),
        Binding("shift+a", "add_site_to_whitelist", "Whitelist", show=False, priority=True),
        Binding("shift+u", "remove_site_from_whitelist", "Unwhitelist", show=False, priority=True),
        Binding("shift+d", "disable_policy", "Disable", show=False, priority=True),
        Binding("shift+e", "enable_policy", "Enable", show=False, priority=True),
        Binding("shift+i", "edit_policy", "Edit Policy", show=False, priority=True),
        Binding("shift+m", "add_editor_policy", "Editor Rule", show=False, priority=True),
        Binding("shift+r", "replay_request", "Replay", show=False, priority=True),
        Binding("shift+t", "toggle_request_follow_top", "Follow Top", show=True, priority=True),
        Binding("shift+v", "toggle_detail_ratio", "Detail Size", show=True, priority=True),
        Binding("shift+x", "remove_policy", "Delete Policy", show=False, priority=True),
    ]

    def __init__(self, controller: RuntimeUIController) -> None:
        super().__init__()
        self._controller = controller

    def compose(self) -> ComposeResult:
        yield RuntimeViewFrame(
            Horizontal(RequestList(), RequestDetailPane(), id="traffic-view"),
            TabbedListPane(),
        )

    def on_mount(self) -> None:
        self.set_interval(0.2, self._tick)
        self.query_one(TabbedListPane).focus_list()
        self._controller.set_active_pane("sites")
        self._refresh_screen()

    def _handle_command_modal_result(self, command: str | None) -> None:
        if command is None:
            self._sync_focus_after_navigation()
            return
        if self._controller.is_help_command(command):
            self._controller.execute_command(command)
            self._refresh_screen()
            self.push_screen(HelpModal(self._controller.build_help_text()))
            return
        self._controller.execute_command(command)
        if self._controller.should_exit:
            self.exit()
            return
        self._refresh_screen()

    @on(RequestList.Highlighted)
    def on_request_list_highlighted(self, event: RequestList.Highlighted) -> None:
        self._controller.set_active_pane("requests")
        self._controller.select_request(event.cursor)
        self._refresh_detail_only()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        widget = event.widget
        if widget.id == "requests":
            self._controller.set_active_pane("requests")
        elif widget.id == "detail-scroll":
            self._controller.set_active_pane("detail")
        elif widget.id == "admin-list":
            self._controller.set_active_pane(cast(ActivePane, self._controller.build_screen_model().admin.active_key))

    def on_key(self, event: events.Key) -> None:
        if event.key == ":" or event.character == ":":
            event.stop()
            event.prevent_default()
            self.action_show_command_modal()
            return
        if self._handle_shortcut_key(event):
            return
        if event.key not in {"tab", "shift+tab"}:
            return
        event.stop()
        event.prevent_default()
        self._cycle_focus(backward=event.key == "shift+tab")

    def _handle_shortcut_key(self, event: events.Key) -> bool:
        focused = self.focused
        if focused is not None and focused.id == "command-input":
            return False

        shortcut = _shortcut_token_from_key_event(key=event.key, character=event.character)
        if shortcut is None:
            return False

        shortcuts: dict[str, Callable[[], None]] = {
            "!": self.action_show_traffic_view,
            "@": self.action_show_admin_view,
            "a": self.action_add_site_to_whitelist,
            "b": self.action_go_back,
            "d": self.action_disable_policy,
            "e": self.action_enable_policy,
            "i": self.action_edit_policy,
            "m": self.action_add_editor_policy,
            "p": self.action_show_policies,
            "r": self.action_replay_request,
            "s": self.action_show_sites,
            "t": self.action_toggle_request_follow_top,
            "u": self.action_remove_site_from_whitelist,
            "v": self.action_toggle_detail_ratio,
            "x": self.action_remove_policy,
        }
        action = shortcuts.get(shortcut)
        if action is None:
            return False
        event.stop()
        event.prevent_default()
        action()
        return True

    @on(RequestList.Selected)
    def on_request_list_selected(self, event: RequestList.Selected) -> None:
        self._controller.set_active_pane("requests")
        self._controller.select_request(event.cursor)
        self._controller.open_selected_request_detail()
        self.query_one(RequestDetailPane).focus_detail()
        self._controller.set_active_pane("detail")
        self._refresh_screen()

    @on(TabbedListPane.Highlighted)
    def on_tabbed_list_highlighted(self, event: TabbedListPane.Highlighted) -> None:
        self._controller.select_aux_item(event.cursor)

    @on(TabbedListPane.Selected)
    def on_tabbed_list_selected(self, event: TabbedListPane.Selected) -> None:
        self._controller.select_aux_item(event.cursor)
        if self._controller.build_screen_model().admin.active_key != "policies":
            return
        self._controller.edit_selected_policy(suspend_ui=self.suspend)
        self._refresh_screen()

    def action_go_back(self) -> None:
        self._controller.go_back()
        self._sync_focus_after_navigation()
        self._refresh_screen()

    def action_show_traffic_view(self) -> None:
        self._controller.switch_view("traffic")
        self.query_one(RequestList).focus_list()
        self._controller.set_active_pane("requests")
        self._refresh_screen()

    def action_show_admin_view(self) -> None:
        self._controller.switch_view("admin")
        self.query_one(TabbedListPane).focus_list()
        self._refresh_screen()

    def action_show_sites(self) -> None:
        self._controller.select_aux_tab("sites")
        self.query_one(TabbedListPane).focus_list()
        self._refresh_screen()

    def action_show_policies(self) -> None:
        self._controller.select_aux_tab("policies")
        self.query_one(TabbedListPane).focus_list()
        self._refresh_screen()

    def action_add_site_to_whitelist(self) -> None:
        self._controller.add_selected_site_to_whitelist()
        self._refresh_screen()

    def action_remove_site_from_whitelist(self) -> None:
        self._controller.remove_selected_site_from_whitelist()
        self._refresh_screen()

    def action_disable_policy(self) -> None:
        self._controller.disable_selected_policy()
        self._refresh_screen()

    def action_enable_policy(self) -> None:
        self._controller.enable_selected_policy()
        self._refresh_screen()

    def action_edit_policy(self) -> None:
        self._controller.edit_selected_policy(suspend_ui=self.suspend)
        self._refresh_screen()

    def action_add_editor_policy(self) -> None:
        self._controller.add_selected_request_to_editor_policy(suspend_ui=self.suspend)
        self._refresh_screen()

    def action_replay_request(self) -> None:
        self._controller.replay_selected_request(suspend_ui=self.suspend)
        self._refresh_screen()

    def action_toggle_request_follow_top(self) -> None:
        self._controller.toggle_request_follow_top()
        self._refresh_screen()

    def action_toggle_detail_ratio(self) -> None:
        self._controller.toggle_detail_ratio()
        self._refresh_screen()

    def action_remove_policy(self) -> None:
        self._controller.remove_selected_policy()
        self._refresh_screen()

    def _tick(self) -> None:
        if not self.query(RequestList) or not self.query("#main-title"):
            return
        self._controller.process_pending_actions(suspend_ui=self.suspend)
        if self._controller.should_exit:
            self.exit()
            return
        self._refresh_screen()

    def _refresh_screen(self) -> None:
        model = self._controller.build_screen_model()
        self._apply_layout(model)
        self.query_one(RequestList).render_model(model.request_list, active=model.active_pane == "requests")
        self.query_one(RequestDetailPane).render_model(
            model.detail,
            active=model.active_pane == "detail",
        )
        self.query_one(TabbedListPane).render_model(
            model.admin,
            active=model.active_pane in {"sites", "policies"},
        )
        self.query_one(StatusFooter).render_model(model.status_bar)
        if self._controller.should_exit:
            self.exit()

    def _refresh_detail_only(self) -> None:
        model = self._controller.build_screen_model()
        self.query_one(RequestDetailPane).render_model(
            model.detail,
            active=model.active_pane == "detail",
        )

    def _apply_layout(self, model: RuntimeScreenModel) -> None:
        plan = determine_runtime_layout(width=self.size.width, model=model)
        traffic_view = self.query_one("#traffic-view", Horizontal)
        traffic_view.display = model.active_view == "traffic"
        traffic_view.styles.layout = plan.content_layout
        admin_view = self.query_one(TabbedListPane)
        admin_view.display = model.active_view == "admin"
        main_pane = self.query_one(RequestList)
        detail_pane = self.query_one(RequestDetailPane)
        detail_pane.display = model.detail_visible

        if plan.content_layout == "vertical":
            if not model.detail_visible or model.detail_ratio == "half":
                main_pane.styles.height = "1fr"
            else:
                main_pane.styles.height = "2fr"
            detail_pane.styles.height = "1fr"
            main_pane.styles.width = "1fr"
            detail_pane.styles.width = "1fr"
        else:
            main_pane.styles.height = "1fr"
            detail_pane.styles.height = "1fr"
            main_pane.styles.width = "1fr" if model.detail_ratio == "half" else "2fr"
            detail_pane.styles.width = "1fr"
        admin_view.styles.height = "1fr"
        admin_view.styles.width = "1fr"

    def _sync_focus_after_navigation(self) -> None:
        model = self._controller.build_screen_model()
        if model.active_view == "admin":
            self.query_one(TabbedListPane).focus_list()
            return
        if model.active_pane == "detail" and model.detail_visible:
            self.query_one(RequestDetailPane).focus_detail()
            self._controller.set_active_pane("detail")
            return
        self.query_one(RequestList).focus_list()
        self._controller.set_active_pane("requests")

    def _cycle_focus(self, *, backward: bool) -> None:
        steps = self._focus_steps()
        current = self._current_focus_step()
        if current not in steps:
            current = "requests"
        index = steps.index(current)
        offset = -1 if backward else 1
        self._focus_step(steps[(index + offset) % len(steps)])

    def _focus_steps(self) -> list[str]:
        model = self._controller.build_screen_model()
        return _focus_step_order(
            active_view=model.active_view,
            detail_visible=model.detail_visible,
            admin_tabs=model.admin.tabs,
        )

    def _current_focus_step(self) -> str:
        focused = self.focused
        if focused is None:
            return "requests"
        model = self._controller.build_screen_model()
        if focused.id == "detail-scroll":
            return f"detail-{model.detail.tab}"
        if focused.id == "admin-list":
            return f"admin-{model.admin.active_key}"
        return "admin-sites" if model.active_view == "admin" else "requests"

    def _focus_step(self, step: str) -> None:
        if step == "requests":
            self.query_one(RequestList).focus_list()
            self._controller.set_active_pane("requests")
            return
        if step == "detail-request":
            self._controller.select_detail_tab("request")
            self.query_one(RequestDetailPane).focus_detail()
            self._refresh_screen()
            return
        if step == "detail-response":
            self._controller.select_detail_tab("response")
            self.query_one(RequestDetailPane).focus_detail()
            self._refresh_screen()
            return
        if step.startswith("admin-"):
            tab_key = step.removeprefix("admin-")
            self._controller.select_aux_tab(tab_key)
            self.query_one(TabbedListPane).focus_list()
            self._refresh_screen()
            return
        self.action_show_command_modal()

    def action_show_command_modal(self) -> None:
        self.push_screen(CommandModal(), self._handle_command_modal_result)


def _shortcut_token_from_key_event(*, key: str, character: str | None) -> str | None:
    known = {"a", "b", "d", "e", "i", "m", "p", "r", "s", "t", "u", "v", "x"}
    normalized_key = key.lower()
    if normalized_key in {"shift+1", "!"} or character == "!":
        return "!"
    if normalized_key in {"shift+2", '"', "@"} or character in {'"', "@"}:
        return "@"
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
