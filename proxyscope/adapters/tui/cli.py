import logging
from typing import Callable

from proxyscope.adapters.tui.components.contracts import ComponentFocus
from proxyscope.adapters.tui.controller import RuntimeController
from proxyscope.adapters.tui.models import DetailTab, RuntimeScreenModel, RuntimeView
from proxyscope.adapters.tui.ui_controller import SuspendUI
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.journal import RequestJournal
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.application.services import RuntimeApplicationServices


class RuntimeCLI(logging.Handler):
    def __init__(
        self,
        *,
        settings: RuntimeSettingsState,
        policies: PolicyAdministrationService,
        configuration: RuntimeConfigurationService,
        request_journal: RequestJournal,
        response_modifier: ResponseModifierService,
        proxy_base_url: str | None = None,
        application_services: RuntimeApplicationServices | None = None,
    ) -> None:
        super().__init__(level=logging.INFO)
        self._shutdown_server: Callable[[], None] | None = None
        self._on_cache_toggle: Callable[[], None] | None = None
        self._controller = RuntimeController(
            settings=settings,
            policies=policies,
            configuration=configuration,
            request_journal=request_journal,
            response_modifier=response_modifier,
            proxy_base_url=proxy_base_url,
            request_shutdown=self._request_shutdown,
            on_cache_toggle=self._trigger_cache_toggle_hook,
            on_log_level_change=self._set_log_level,
            application_services=application_services,
        )

    @property
    def should_exit(self) -> bool:
        return self._controller.should_exit

    def set_active_focus(self, focus: ComponentFocus) -> None:
        self._controller.set_active_focus(focus)

    def switch_view(self, view: RuntimeView) -> None:
        self._controller.switch_view(view)

    def select_request(self, cursor: int) -> None:
        self._controller.select_request(cursor)

    def toggle_request_follow_top(self) -> None:
        self._controller.toggle_request_follow_top()

    def open_selected_request_detail(self) -> None:
        self._controller.open_selected_request_detail()

    def select_detail_tab(self, tab: DetailTab) -> None:
        self._controller.select_detail_tab(tab)

    def toggle_detail_ratio(self) -> None:
        self._controller.toggle_detail_ratio()

    def select_aux_tab(self, tab_key: str) -> None:
        self._controller.select_aux_tab(tab_key)

    def select_aux_item(self, cursor: int) -> None:
        self._controller.select_aux_item(cursor)

    def go_back(self) -> None:
        self._controller.go_back()

    def add_selected_site_to_whitelist(self) -> None:
        self._controller.add_selected_site_to_whitelist()

    def remove_selected_site_from_whitelist(self) -> None:
        self._controller.remove_selected_site_from_whitelist()

    def enable_selected_policy(self) -> None:
        self._controller.enable_selected_policy()

    def disable_selected_policy(self) -> None:
        self._controller.disable_selected_policy()

    def remove_selected_policy(self) -> None:
        self._controller.remove_selected_policy()

    def edit_selected_policy(self, *, suspend_ui: SuspendUI | None = None) -> None:
        self._controller.edit_selected_policy(suspend_ui=suspend_ui)

    def add_selected_request_to_editor_policy(self, *, suspend_ui: SuspendUI | None = None) -> None:
        self._controller.add_selected_request_to_editor_policy(suspend_ui=suspend_ui)

    def replay_selected_request(self, *, suspend_ui: SuspendUI | None = None) -> None:
        self._controller.replay_selected_request(suspend_ui=suspend_ui)

    def process_pending_actions(self, *, suspend_ui: SuspendUI | None = None) -> None:
        self._controller.process_pending_actions(suspend_ui=suspend_ui)

    def execute_command(self, command: str) -> bool:
        return self._controller.execute_command(command)

    def is_help_command(self, command: str) -> bool:
        return self._controller.is_help_command(command)

    def build_help_text(self) -> str:
        return self._controller.build_help_text()

    def build_screen_model(self) -> RuntimeScreenModel:
        return self._controller.build_screen_model()

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        self._controller.set_status_message(self.format(record))

    def on_site_visit(self, host: str) -> None:
        self._controller.record_site_visit(host)

    def run(
        self,
        *,
        shutdown_server: Callable[[], None],
        on_cache_toggle: Callable[[], None] | None = None,
    ) -> None:
        self._shutdown_server = shutdown_server
        self._on_cache_toggle = on_cache_toggle
        from proxyscope.adapters.tui.textual import RuntimeTextualApp

        RuntimeTextualApp(self).run()

    def _request_shutdown(self) -> None:
        if self._shutdown_server is not None:
            self._shutdown_server()

    def _trigger_cache_toggle_hook(self) -> None:
        if self._on_cache_toggle is None:
            return
        try:
            self._on_cache_toggle()
        except Exception as exc:  # noqa: BLE001
            self._controller.set_status_message(f"Failed to close active SSL tunnels: {exc}")

    def _set_log_level(self, level: int) -> None:
        logging.getLogger().setLevel(level)
