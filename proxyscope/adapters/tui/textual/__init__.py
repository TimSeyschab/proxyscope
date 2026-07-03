from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input

from proxyscope.adapters.tui.components import (
    CommandModal,
    RequestDetailPane,
    RequestList,
    RuntimeScreenLayout,
    StatusFooter,
    TabbedListPane,
    TrafficViewPane,
)
from proxyscope.adapters.tui.components.contracts import ComponentFocus
from proxyscope.adapters.tui.models import RuntimeScreenModel
from proxyscope.adapters.tui.navigation import focus_step_order as _focus_step_order
from proxyscope.adapters.tui.textual.modals import HelpModal, RequestPolicyPickerModal, RequestPolicySelection
from proxyscope.adapters.tui.ui_controller import RuntimeUIController

RuntimeContentLayout = Literal["horizontal", "vertical"]


@dataclass(frozen=True)
class RuntimeLayoutPlan:
    content_layout: RuntimeContentLayout


def determine_runtime_layout(*, width: int, model: RuntimeScreenModel) -> RuntimeLayoutPlan:
    content_layout: RuntimeContentLayout = "horizontal"

    if width < 100:
        content_layout = "vertical"

    return RuntimeLayoutPlan(content_layout=content_layout)


class RuntimeTextualApp(App[None]):
    CSS_PATH = Path(__file__).resolve().parents[1] / "runtime.tcss"

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
        Binding("shift+m", "open_policy_picker", "Policy Picker", show=False, priority=True),
        Binding("shift+r", "replay_request", "Replay", show=False, priority=True),
        Binding("shift+t", "toggle_request_follow_top", "Follow Top", show=True, priority=True),
        Binding("shift+v", "toggle_detail_ratio", "Detail Size", show=True, priority=True),
        Binding("shift+x", "remove_policy", "Delete Policy", show=False, priority=True),
    ]

    def __init__(self, controller: RuntimeUIController) -> None:
        super().__init__()
        self._controller = controller
        self._focused_target: ComponentFocus | None = None

    def compose(self) -> ComposeResult:
        yield RuntimeScreenLayout(
            TrafficViewPane(),
            TabbedListPane(),
        )

    def on_mount(self) -> None:
        self.set_interval(0.2, self._tick)
        self.query_one(TabbedListPane).focus_list()
        self._activate_focus(TabbedListPane.focus_target("sites"))
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
        self._controller.select_request(event.cursor)
        self._refresh_detail_only()

    @on(RequestList.Focused)
    def on_request_list_focused(self) -> None:
        self._activate_focus(RequestList.focus_target)

    @on(RequestDetailPane.Focused)
    def on_request_detail_focused(self) -> None:
        model = self._controller.build_screen_model()
        self._activate_focus(RequestDetailPane.focus_target(model.detail.tab))

    @on(TabbedListPane.Focused)
    def on_tabbed_list_focused(self) -> None:
        active_key = self._controller.build_screen_model().admin.active_key
        self._activate_focus(TabbedListPane.focus_target(active_key))

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
        if isinstance(focused, Input):
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
            "m": self.action_open_policy_picker,
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
        self._controller.set_active_focus(RequestList.focus_target)
        self._controller.select_request(event.cursor)
        self._controller.open_selected_request_detail()
        self.query_one(TrafficViewPane).focus_detail()
        model = self._controller.build_screen_model()
        self._activate_focus(RequestDetailPane.focus_target(model.detail.tab))
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
        self._controller.switch_view(TrafficViewPane.component_id.value)
        self.query_one(TrafficViewPane).focus_requests()
        self._activate_focus(RequestList.focus_target)
        self._refresh_screen()

    def action_show_admin_view(self) -> None:
        self._controller.switch_view(TabbedListPane.component_id.value)
        self.query_one(TabbedListPane).focus_list()
        model = self._controller.build_screen_model()
        self._activate_focus(TabbedListPane.focus_target(model.admin.active_key))
        self._refresh_screen()

    def action_show_sites(self) -> None:
        self._controller.select_aux_tab("sites")
        self.query_one(TabbedListPane).focus_list()
        self._activate_focus(TabbedListPane.focus_target("sites"))
        self._refresh_screen()

    def action_show_policies(self) -> None:
        self._controller.select_aux_tab("policies")
        self.query_one(TabbedListPane).focus_list()
        self._activate_focus(TabbedListPane.focus_target("policies"))
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

    def action_open_policy_picker(self) -> None:
        self.push_screen(
            RequestPolicyPickerModal(include_static_response=self._controller.selected_request_has_response()),
            self._handle_policy_picker_result,
        )

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
        if not self.query(TrafficViewPane) or not self.query(StatusFooter):
            return
        self._controller.process_pending_actions(suspend_ui=self.suspend)
        if self._controller.should_exit:
            self.exit()
            return
        self._refresh_screen()

    def _refresh_screen(self) -> None:
        model = self._controller.build_screen_model()
        self._apply_layout(model)
        self.query_one(TrafficViewPane).render_model(model)
        self.query_one(TabbedListPane).render_model(
            model.admin,
            active=model.active_view == TabbedListPane.component_id.value,
        )
        self.query_one(StatusFooter).render_model(model.status_bar)
        if self._controller.should_exit:
            self.exit()

    def _refresh_detail_only(self) -> None:
        model = self._controller.build_screen_model()
        self.query_one(TrafficViewPane).render_detail(model)

    def _apply_layout(self, model: RuntimeScreenModel) -> None:
        plan = determine_runtime_layout(width=self.size.width, model=model)
        traffic_view = self.query_one(TrafficViewPane)
        traffic_view.display = model.active_view == TrafficViewPane.component_id.value
        traffic_view.apply_layout(content_layout=plan.content_layout, model=model)
        admin_view = self.query_one(TabbedListPane)
        admin_view.display = model.active_view == TabbedListPane.component_id.value
        admin_view.styles.height = "1fr"
        admin_view.styles.width = "1fr"

    def _sync_focus_after_navigation(self) -> None:
        model = self._controller.build_screen_model()
        if model.active_view == TabbedListPane.component_id.value:
            self.query_one(TabbedListPane).focus_list()
            self._activate_focus(TabbedListPane.focus_target(model.admin.active_key))
            return
        if model.active_pane == RequestDetailPane.focus_target(model.detail.tab).pane_key and model.detail_visible:
            self.query_one(TrafficViewPane).focus_detail()
            self._activate_focus(RequestDetailPane.focus_target(model.detail.tab))
            return
        self.query_one(TrafficViewPane).focus_requests()
        self._activate_focus(RequestList.focus_target)

    def _cycle_focus(self, *, backward: bool) -> None:
        steps = self._focus_steps()
        if not steps:
            return
        current = self._current_focus_step()
        if current not in steps:
            self._focus_step(self._fallback_focus_step(steps))
            return
        index = steps.index(current)
        offset = -1 if backward else 1
        self._focus_step(steps[(index + offset) % len(steps)])

    def _focus_steps(self) -> list[ComponentFocus]:
        model = self._controller.build_screen_model()
        return _focus_step_order(
            active_view=model.active_view,
            detail_visible=model.detail_visible,
            admin_tabs=model.admin.tabs,
        )

    def _current_focus_step(self) -> ComponentFocus | None:
        model = self._controller.build_screen_model()
        if self._focused_target is None or self._focused_target.component_id.value != model.active_view:
            return None
        if RequestDetailPane.owns_focus(self._focused_target) and model.detail_visible:
            return RequestDetailPane.focus_target(model.detail.tab)
        if TabbedListPane.owns_focus(self._focused_target):
            return TabbedListPane.focus_target(model.admin.active_key)
        if RequestList.owns_focus(self._focused_target):
            return RequestList.focus_target
        return None

    def _fallback_focus_step(self, steps: list[ComponentFocus]) -> ComponentFocus:
        model = self._controller.build_screen_model()
        if model.active_view == TabbedListPane.component_id.value:
            active_admin_step = TabbedListPane.focus_target(model.admin.active_key)
            if active_admin_step in steps:
                return active_admin_step
        if model.active_view == TrafficViewPane.component_id.value and model.detail_visible:
            active_detail_step = RequestDetailPane.focus_target(model.detail.tab)
            if active_detail_step in steps:
                return active_detail_step
        if RequestList.focus_target in steps:
            return RequestList.focus_target
        return steps[0]

    def _focus_step(self, step: ComponentFocus) -> None:
        if RequestList.owns_focus(step):
            self.query_one(TrafficViewPane).focus_requests()
            self._activate_focus(step)
            return
        if RequestDetailPane.owns_focus(step):
            detail_tab = RequestDetailPane.tab_key_from_focus(step)
            self._controller.select_detail_tab(detail_tab)
            self.query_one(TrafficViewPane).focus_detail()
            self._activate_focus(step)
            self._refresh_screen()
            return
        if TabbedListPane.owns_focus(step):
            tab_key = TabbedListPane.tab_key_from_focus(step)
            self._controller.select_aux_tab(tab_key)
            self.query_one(TabbedListPane).focus_list()
            self._activate_focus(step)
            self._refresh_screen()
            return
        self.action_show_command_modal()

    def _activate_focus(self, focus: ComponentFocus) -> None:
        self._focused_target = focus
        self._controller.set_active_focus(focus)

    def action_show_command_modal(self) -> None:
        self.push_screen(CommandModal(), self._handle_command_modal_result)

    def _handle_policy_picker_result(self, selection: RequestPolicySelection | None) -> None:
        if selection is None:
            self._sync_focus_after_navigation()
            return
        self._controller.apply_selected_request_policy_action(
            target=selection.target,
            action=selection.action,
            suspend_ui=self.suspend,
        )
        self._refresh_screen()


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
