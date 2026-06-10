from dataclasses import dataclass
from typing import Callable, Literal

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from proxyscope.app.runtime.ui_components import AuxSidebar, CommandBar, RequestDetailPane, RequestList
from proxyscope.app.runtime.ui_components.rendering import (
    plain_text as _plain_text,
)
from proxyscope.app.runtime.ui_controller import RuntimeUIController
from proxyscope.app.runtime.ui_models import RuntimeScreenModel
from proxyscope.app.runtime.ui_navigation import focus_step_order as _focus_step_order

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
    show_sidebar = model.aux.visible
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
    CSS_PATH = "runtime.tcss"

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

    def __init__(self, controller: RuntimeUIController) -> None:
        super().__init__()
        self._controller = controller

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            with Horizontal(id="content"):
                yield RequestList()
                yield RequestDetailPane()
                yield AuxSidebar()
            yield CommandBar()

    def on_mount(self) -> None:
        self.set_interval(0.2, self._tick)
        self.query_one(RequestList).focus_list()
        self._controller.set_active_pane("requests")
        self._refresh_screen()

    @on(CommandBar.Submitted)
    def on_command_bar_submitted(self, event: CommandBar.Submitted) -> None:
        command = event.command
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
        elif widget.id == "sidebar-list":
            self._controller.set_active_pane("aux")

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

    @on(RequestList.Selected)
    def on_request_list_selected(self, event: RequestList.Selected) -> None:
        self._controller.set_active_pane("requests")
        self._controller.select_request(event.cursor)
        self._controller.open_selected_request_detail()
        self.query_one(RequestDetailPane).focus_detail()
        self._controller.set_active_pane("detail")
        self._refresh_screen()

    @on(AuxSidebar.Highlighted)
    def on_aux_sidebar_highlighted(self, event: AuxSidebar.Highlighted) -> None:
        self._controller.select_aux_item(event.cursor)

    @on(AuxSidebar.Selected)
    def on_aux_sidebar_selected(self, event: AuxSidebar.Selected) -> None:
        self._controller.select_aux_item(event.cursor)
        if self._controller.build_screen_model().aux.active_key != "policies":
            return
        self._controller.edit_selected_policy(suspend_ui=self.suspend)
        self._refresh_screen()

    def action_go_back(self) -> None:
        self._controller.go_back()
        self._sync_focus_after_navigation()
        self._refresh_screen()

    def action_toggle_sites_sidebar(self) -> None:
        model = self._controller.build_screen_model()
        if model.aux.visible and model.aux.active_key == "sites":
            self._controller.toggle_aux_visibility()
            self._sync_focus_after_navigation()
            self._refresh_screen()
            return
        self._controller.select_aux_tab("sites")
        self.query_one(AuxSidebar).focus_sidebar()
        self._refresh_screen()

    def action_show_policies(self) -> None:
        self._controller.select_aux_tab("policies")
        self.query_one(AuxSidebar).focus_sidebar()
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

    def action_remove_policy(self) -> None:
        self._controller.remove_selected_policy()
        self._refresh_screen()

    def _tick(self) -> None:
        if not self.query(RequestList):
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
            main_mode=model.main_mode,
            active=model.active_pane == "detail",
        )
        self.query_one(AuxSidebar).render_model(model.aux, active=model.active_pane == "aux")
        self.query_one(CommandBar).render_model(model.status_bar)
        if self._controller.should_exit:
            self.exit()

    def _refresh_detail_only(self) -> None:
        model = self._controller.build_screen_model()
        self.query_one(RequestDetailPane).render_model(
            model.detail,
            main_mode=model.main_mode,
            active=model.active_pane == "detail",
        )

    def _apply_layout(self, model: RuntimeScreenModel) -> None:
        plan = determine_runtime_layout(width=self.size.width, model=model)
        content = self.query_one("#content", Horizontal)
        content.styles.layout = plan.content_layout
        main_pane = self.query_one(RequestList)
        detail_pane = self.query_one(RequestDetailPane)
        sidebar_pane = self.query_one(AuxSidebar)

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
        model = self._controller.build_screen_model()
        if model.active_pane == "aux" and model.aux.visible:
            self.query_one(AuxSidebar).focus_sidebar()
            return
        if model.main_mode == "request_detail":
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
            main_mode=model.main_mode,
            aux_visible=model.aux.visible,
            aux_tabs=model.aux.aux_tabs,
        )

    def _current_focus_step(self) -> str:
        focused = self.focused
        if focused is None:
            return "requests"
        model = self._controller.build_screen_model()
        if focused.id == "detail-scroll":
            return f"detail-{model.detail.tab}"
        if focused.id == "sidebar-list":
            return f"aux-{model.aux.active_key}"
        if focused.id == "command-input":
            return "command"
        return "requests"

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
        if step.startswith("aux-"):
            tab_key = step.removeprefix("aux-")
            self._controller.select_aux_tab(tab_key)
            self.query_one(AuxSidebar).focus_sidebar()
            self._refresh_screen()
            return
        self.query_one(CommandBar).focus_input()


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
