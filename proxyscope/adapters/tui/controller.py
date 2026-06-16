from typing import Callable

from proxyscope.adapters.factory import create_default_runtime_application_services
from proxyscope.adapters.tui.models import ActivePane, DetailTab, RuntimeScreenModel, RuntimeView
from proxyscope.adapters.tui.navigation import RuntimeUINavigationService
from proxyscope.adapters.tui.presenter import build_runtime_screen_model
from proxyscope.adapters.tui.state import RuntimeUIViewState
from proxyscope.adapters.tui.ui_controller import SuspendUI
from proxyscope.application.commands import create_runtime_command_registry
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.journal import RequestJournal
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.application.services import RuntimeApplicationServices
from proxyscope.policies.models import PolicyRule, StaticResponseAction

REQUEST_LIST_WINDOW_SIZE = 250


class RuntimeController:
    def __init__(
        self,
        *,
        settings: RuntimeSettingsState,
        policies: PolicyAdministrationService,
        configuration: RuntimeConfigurationService,
        request_journal: RequestJournal,
        response_modifier: ResponseModifierService,
        proxy_base_url: str | None = None,
        request_shutdown: Callable[[], None] | None = None,
        on_cache_toggle: Callable[[], None] | None = None,
        on_log_level_change: Callable[[int], None] | None = None,
        application_services: RuntimeApplicationServices | None = None,
    ) -> None:
        self._settings = settings
        self._policies = policies
        self._configuration = configuration
        self._request_shutdown = request_shutdown
        self._on_cache_toggle = on_cache_toggle
        self._on_log_level_change = on_log_level_change
        self._view_state = RuntimeUIViewState()
        self._ui_navigation = RuntimeUINavigationService(self._view_state)
        self._services = application_services or create_default_runtime_application_services(
            settings=settings,
            policies=policies,
            configuration=configuration,
            request_journal=request_journal,
            response_modifier=response_modifier,
            proxy_base_url=proxy_base_url,
        )
        self._command_registry = create_runtime_command_registry(
            self._services,
            request_shutdown=self._request_shutdown,
            on_cache_toggle=self._trigger_cache_toggle_hook,
            on_schedule_policy_edit=self._schedule_policy_edit,
        )

    @property
    def status_message(self) -> str:
        return self._view_state.status_message

    @property
    def help_summary(self) -> str:
        return self._command_registry.build_help_summary()

    @property
    def pending_policy_edit_name(self) -> str | None:
        return self._services.policies.pending_edit_name

    @property
    def should_exit(self) -> bool:
        return self._view_state.should_exit

    def set_status_message(self, message: str) -> None:
        self._view_state.status_message = message

    def set_active_pane(self, pane: ActivePane) -> None:
        self._ui_navigation.set_active_pane(pane)

    def switch_view(self, view: RuntimeView) -> None:
        self._ui_navigation.switch_view(view)

    def select_request(self, cursor: int) -> None:
        if self._view_state.request_follow_top and cursor != 0:
            self._view_state.request_follow_top = False
        self._ui_navigation.select_request(self._services.requests.list_entries(), cursor)

    def toggle_request_follow_top(self) -> None:
        self._view_state.request_follow_top = not self._view_state.request_follow_top
        if self._view_state.request_follow_top:
            self._ui_navigation.select_request(self._services.requests.list_entries(), 0)
            self._view_state.status_message = "Request list follows the newest request."
            return
        self._view_state.status_message = "Request list keeps the selected request stable."

    def open_selected_request_detail(self) -> None:
        if not self._ui_navigation.open_selected_request_detail(self._services.requests.list_entries()):
            self._view_state.status_message = "No requests available."

    def select_detail_tab(self, tab: DetailTab) -> None:
        self._ui_navigation.select_detail_tab(tab)

    def toggle_detail_ratio(self) -> None:
        self._ui_navigation.toggle_detail_ratio()
        ratio = self._view_state.detail_ratio
        ratio_text = "1/2" if ratio == "half" else "1/3"
        self._view_state.status_message = f"Detail width set to {ratio_text}."

    def select_aux_tab(self, tab_key: str) -> None:
        self._ui_navigation.select_aux_tab(tab_key)

    def select_aux_item(self, cursor: int) -> None:
        self._ui_navigation.select_aux_item(cursor)

    def toggle_aux_visibility(self) -> None:
        self._ui_navigation.switch_view("admin")

    def go_back(self) -> None:
        if not self._ui_navigation.go_back():
            self._view_state.status_message = "Nothing to close."

    def add_selected_site_to_whitelist(self) -> None:
        selected = self._selected_site()
        if not selected:
            self._view_state.status_message = "No site selected."
            return
        self._view_state.status_message = self._services.settings.add_whitelist_entry(selected)

    def remove_selected_site_from_whitelist(self) -> None:
        selected = self._selected_site()
        if not selected:
            self._view_state.status_message = "No site selected."
            return
        self._view_state.status_message = self._services.settings.remove_whitelist_entry(selected)

    def enable_selected_policy(self) -> None:
        if not self._ensure_policy_tab_active():
            return
        self._view_state.status_message = self._services.policies.set_enabled(
            self._selected_policy_name(),
            enabled=True,
        )

    def disable_selected_policy(self) -> None:
        if not self._ensure_policy_tab_active():
            return
        self._view_state.status_message = self._services.policies.set_enabled(
            self._selected_policy_name(),
            enabled=False,
        )

    def remove_selected_policy(self) -> None:
        if not self._ensure_policy_tab_active():
            return
        self._view_state.status_message = self._services.policies.remove(self._selected_policy_name())

    def edit_selected_policy(self, *, suspend_ui: SuspendUI | None = None) -> None:
        if not self._ensure_policy_tab_active():
            return
        self._view_state.status_message = self._services.policies.edit(
            self._selected_policy_name(),
            suspend_ui=suspend_ui,
        )

    def add_selected_request_to_editor_policy(self, *, suspend_ui: SuspendUI | None = None) -> None:
        selected = self._ui_navigation.selected_request(self._services.requests.list_entries())
        if selected is None:
            self._view_state.status_message = "No request selected."
            return
        self._view_state.status_message = self._services.policies.add_request_to_editor_policy(
            selected,
            suspend_ui=suspend_ui,
        )

    def replay_selected_request(self, *, suspend_ui: SuspendUI | None = None) -> None:
        selected = self._ui_navigation.selected_request(self._services.requests.list_entries())
        if selected is None:
            self._view_state.status_message = "No request selected."
            return
        self._view_state.status_message = self._services.replay.replay(selected, suspend_ui=suspend_ui)

    def process_pending_actions(self, *, suspend_ui: SuspendUI | None = None) -> None:
        message = self._services.policies.process_pending_edit(suspend_ui=suspend_ui)
        if message is not None:
            self._view_state.status_message = message
        message = self._services.response_edits.process_pending_edit(suspend_ui=suspend_ui)
        if message is not None:
            self._view_state.status_message = message

    def record_site_visit(self, host: str) -> None:
        self._services.requests.record_site_visit(host)

    def execute_command(self, command: str) -> bool:
        normalized = command.strip()
        if not normalized:
            return False

        result = self._command_registry.dispatch(normalized)
        if result is None:
            self._view_state.status_message = f"Unknown command: {command}"
            return False
        if result.requests_changed:
            self._reset_request_view_after_filter_change()
        if result.updated_log_level is not None and self._on_log_level_change is not None:
            self._on_log_level_change(result.updated_log_level)
        self._view_state.status_message = result.status_message
        self._view_state.should_exit = result.should_exit
        return result.should_exit

    def is_help_command(self, command: str) -> bool:
        return self._command_registry.contains(command, command_name="help")

    def build_help_text(self) -> str:
        return self._command_registry.build_help_text() + (
            "\n\nNavigation\n"
            "  :                            Open command prompt.\n"
            "  Enter on a request          Open request detail.\n"
            "  Enter on a policy           Open policy editor (Policies tab).\n"
            "  Empty command / Esc          Close command prompt.\n"
            "  Tab / Shift+Tab             Move forward or backward through view panes.\n"
            "  Shift+1                     Show Requests view.\n"
            "  Shift+2                     Show Sites/Policies view.\n"
            "  Shift+S                     Show Sites tab.\n"
            "  Shift+P                     Show Policies tab.\n"
            "  Shift+B                     Close request detail.\n"
            "  Shift+V                     Toggle request detail width (1/3 or 1/2).\n"
            "  Shift+A                     Add the selected site to the whitelist.\n"
            "  Shift+U                     Remove the selected site from the whitelist.\n"
            "  Shift+D                     Disable the selected policy (Policies tab).\n"
            "  Shift+E                     Enable the selected policy (Policies tab).\n"
            "  Shift+I                     Edit the selected policy (Policies tab).\n"
            "  Shift+M                     Add and edit selected request as editor policy.\n"
            "  Shift+R                     Replay the selected request after editing.\n"
            "  Shift+T                     Toggle following the newest request at the top.\n"
            "  Shift+X                     Remove the selected policy (Policies tab).\n"
            "  Shift+<letter>              Terminal sends uppercase character (e.g. Shift+M == M).\n"
            "  Esc / Enter                 Close this help dialog."
        )

    def _reset_request_view_after_filter_change(self) -> None:
        self._ui_navigation.reset_request_view(has_entries=bool(self._services.requests.list_entries()))

    def _ordered_policy_items(self) -> list[tuple[str, str]]:
        rules = self._policies.sorted_rules()
        return [(rule.name, _format_policy_item(rule)) for rule in rules]

    def _selected_site(self) -> str | None:
        return self._ui_navigation.selected_site(self._services.requests.site_names())

    def _selected_policy_name(self) -> str | None:
        policy_names = [name for name, _description in self._ordered_policy_items()]
        return self._ui_navigation.selected_policy_name(policy_names)

    def _ensure_policy_tab_active(self) -> bool:
        if self._ui_navigation.is_policy_tab_active():
            return True
        self._view_state.status_message = "Open Policies tab first (Shift+2, Shift+P)."
        return False

    def _schedule_policy_edit(self, name: str) -> None:
        self._services.policies.schedule_edit(name)

    def _trigger_cache_toggle_hook(self) -> None:
        if self._on_cache_toggle is None:
            return
        try:
            self._on_cache_toggle()
        except Exception as exc:  # noqa: BLE001
            self._view_state.status_message = f"Failed to close active SSL tunnels: {exc}"

    def build_screen_model(self) -> "RuntimeScreenModel":
        entries = self._services.requests.list_entries()
        self._ui_navigation.sync_request_selection(entries, follow_top=self._view_state.request_follow_top)
        request_window = self._services.requests.list_window(
            cursor=self._view_state.request_cursor,
            limit=REQUEST_LIST_WINDOW_SIZE,
        )

        policy_items = [description for _name, description in self._ordered_policy_items()]
        self._ui_navigation.clamp_policy_cursor(len(policy_items))

        return build_runtime_screen_model(
            state=self._view_state,
            settings=self._settings,
            policies=self._policies,
            configuration=self._configuration,
            request_window=request_window,
            site_counter=self._services.requests.site_counter(),
            policy_items=policy_items,
            filter_summary=self._services.requests.filter_summary,
        )


def _format_policy_item(rule: PolicyRule) -> str:
    state = "ON" if rule.enabled else "OFF"
    method = ",".join(rule.match.methods or ("*",))
    target = rule.match.url_exact or rule.match.url_prefix or "*"
    if isinstance(rule.action, StaticResponseAction):
        return f"{state:>3} p={rule.priority} {rule.name} | static {method} {target} -> {rule.action.status_code}"
    return f"{state:>3} p={rule.priority} {rule.name} | open_editor {method} {target}"
