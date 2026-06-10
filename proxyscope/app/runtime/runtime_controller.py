import json
from collections import Counter
from dataclasses import dataclass
from threading import Lock
from typing import Callable

from proxyscope.app.config.runtime import PolicyRule, RuntimeConfig
from proxyscope.app.editing.modifier import ResponseModifierService
from proxyscope.app.runtime.actions import (
    RuntimePolicyActionService,
    RuntimeReplayActionService,
    RuntimeResponseEditActionService,
)
from proxyscope.app.runtime.commands import RuntimeCommandService
from proxyscope.app.runtime.exporting import export_entries, load_entries_from_json
from proxyscope.app.runtime.journal import LoggedExchange, RequestJournal
from proxyscope.app.runtime.ui_controller import SuspendUI
from proxyscope.app.runtime.ui_models import ActivePane, DetailTab, RuntimeScreenModel
from proxyscope.app.runtime.ui_navigation import RuntimeUINavigationService
from proxyscope.app.runtime.ui_presenter import build_runtime_screen_model
from proxyscope.app.runtime.ui_state import RuntimeUIViewState


@dataclass
class RequestFilterState:
    host: str | None = None
    method: str | None = None
    status_code: int | None = None
    text: str | None = None

    def is_active(self) -> bool:
        return any((self.host, self.method, self.status_code is not None, self.text))

    def summary(self) -> str:
        parts: list[str] = []
        if self.host:
            parts.append(f"host={self.host}")
        if self.method:
            parts.append(f"method={self.method}")
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.text:
            parts.append(f"text={self.text}")
        return " ".join(parts) if parts else "off"

    def matches(self, entry: LoggedExchange) -> bool:
        if self.host is not None and (entry.target_host or "").lower() != self.host:
            return False
        if self.method is not None and entry.request.method.upper() != self.method:
            return False
        if self.status_code is not None:
            if entry.response is None or entry.response.status_code != self.status_code:
                return False
        if self.text is not None:
            haystack = _entry_search_text(entry)
            if self.text not in haystack:
                return False
        return True

    def clear(self) -> None:
        self.host = None
        self.method = None
        self.status_code = None
        self.text = None


class RuntimeController:
    HELP_SUMMARY = (
        "Commands: help | clear | sites | loglevel <LEVEL> | "
        "filter [show|clear|host|method|status|text] ... | find <text>|find clear | "
        "export <json|har> <path> | "
        "session <save|load> <path> | "
        "mitm [show|on|off|certs-dir <path>] | "
        "whitelist [add|remove|clear|show] ... | cache [show|on|off|toggle] | "
        "config [show|save [path]|reload] | "
        "policy [show|add-editor|add-editor-prefix|remove-editor|clear-editor|"
        "add-static|add-static-prefix|set-priority|edit|remove|enable|disable] ... | "
        "Hotkeys (Shift): A/B/D/E/I/M/P/R/S/U/X | quit"
    )

    def __init__(
        self,
        *,
        runtime_config: RuntimeConfig,
        request_journal: RequestJournal,
        response_modifier: ResponseModifierService,
        proxy_base_url: str | None = None,
        request_shutdown: Callable[[], None] | None = None,
        on_cache_toggle: Callable[[], None] | None = None,
        on_log_level_change: Callable[[int], None] | None = None,
    ) -> None:
        self._runtime_config = runtime_config
        self._request_journal = request_journal
        self._proxy_base_url = proxy_base_url
        self._sites: Counter[str] = Counter()
        self._lock = Lock()
        self._request_shutdown = request_shutdown
        self._on_cache_toggle = on_cache_toggle
        self._on_log_level_change = on_log_level_change
        self._request_filter = RequestFilterState()
        self._view_state = RuntimeUIViewState()
        self._ui_navigation = RuntimeUINavigationService(self._view_state)
        self._policy_actions = RuntimePolicyActionService(self._runtime_config)
        self._replay_actions = RuntimeReplayActionService(proxy_base_url=self._proxy_base_url)
        self._response_edit_actions = RuntimeResponseEditActionService(response_modifier)
        self._command_service = RuntimeCommandService(runtime_config=self._runtime_config)

    @property
    def status_message(self) -> str:
        return self._view_state.status_message

    @property
    def pending_policy_edit_name(self) -> str | None:
        return self._policy_actions.pending_edit_name

    @property
    def should_exit(self) -> bool:
        return self._view_state.should_exit

    def set_status_message(self, message: str) -> None:
        self._view_state.status_message = message

    def set_active_pane(self, pane: ActivePane) -> None:
        self._ui_navigation.set_active_pane(pane)

    def select_request(self, cursor: int) -> None:
        self._ui_navigation.select_request(self._ordered_entries(), cursor)

    def open_selected_request_detail(self) -> None:
        if not self._ui_navigation.open_selected_request_detail(self._ordered_entries()):
            self._view_state.status_message = "No requests available."

    def select_detail_tab(self, tab: DetailTab) -> None:
        self._ui_navigation.select_detail_tab(tab)

    def select_aux_tab(self, tab_key: str) -> None:
        self._ui_navigation.select_aux_tab(tab_key)

    def select_aux_item(self, cursor: int) -> None:
        self._ui_navigation.select_aux_item(cursor)

    def toggle_aux_visibility(self) -> None:
        self._ui_navigation.toggle_aux_visibility()

    def go_back(self) -> None:
        if not self._ui_navigation.go_back():
            self._view_state.status_message = "Nothing to close."

    def add_selected_site_to_whitelist(self) -> None:
        selected = self._selected_site()
        if not selected:
            self._view_state.status_message = "No site selected."
            return
        added = self._runtime_config.add_whitelist_entry(selected)
        self._view_state.status_message = f"Added selected site to whitelist: {added}"

    def remove_selected_site_from_whitelist(self) -> None:
        selected = self._selected_site()
        if not selected:
            self._view_state.status_message = "No site selected."
            return
        removed = self._runtime_config.remove_whitelist_entry(selected)
        if removed:
            self._view_state.status_message = f"Removed selected site from whitelist: {selected}"
        else:
            self._view_state.status_message = f"Selected site not in whitelist: {selected}"

    def enable_selected_policy(self) -> None:
        if not self._ensure_policy_tab_active():
            return
        self._view_state.status_message = self._policy_actions.set_enabled(
            self._selected_policy_name(),
            enabled=True,
        )

    def disable_selected_policy(self) -> None:
        if not self._ensure_policy_tab_active():
            return
        self._view_state.status_message = self._policy_actions.set_enabled(
            self._selected_policy_name(),
            enabled=False,
        )

    def remove_selected_policy(self) -> None:
        if not self._ensure_policy_tab_active():
            return
        self._view_state.status_message = self._policy_actions.remove(self._selected_policy_name())

    def edit_selected_policy(self, *, suspend_ui: SuspendUI | None = None) -> None:
        if not self._ensure_policy_tab_active():
            return
        self._view_state.status_message = self._policy_actions.edit(
            self._selected_policy_name(),
            suspend_ui=suspend_ui,
        )

    def add_selected_request_to_editor_policy(self, *, suspend_ui: SuspendUI | None = None) -> None:
        selected = self._ui_navigation.selected_request(self._ordered_entries())
        if selected is None:
            self._view_state.status_message = "No request selected."
            return
        self._view_state.status_message = self._policy_actions.add_request_to_editor_policy(
            selected,
            suspend_ui=suspend_ui,
        )

    def replay_selected_request(self, *, suspend_ui: SuspendUI | None = None) -> None:
        selected = self._ui_navigation.selected_request(self._ordered_entries())
        if selected is None:
            self._view_state.status_message = "No request selected."
            return
        self._view_state.status_message = self._replay_actions.replay(selected, suspend_ui=suspend_ui)

    def process_pending_actions(self, *, suspend_ui: SuspendUI | None = None) -> None:
        message = self._policy_actions.process_pending_edit(suspend_ui=suspend_ui)
        if message is not None:
            self._view_state.status_message = message
        message = self._response_edit_actions.process_pending_edit(suspend_ui=suspend_ui)
        if message is not None:
            self._view_state.status_message = message

    def record_site_visit(self, host: str) -> None:
        with self._lock:
            self._sites[host] += 1

    def execute_command(self, command: str) -> bool:
        normalized = command.strip()
        if not normalized:
            return False

        parts = normalized.split()
        cmd = parts[0].lower()

        if cmd in {"q", "quit", "exit"}:
            self._view_state.status_message = "Shutting down server..."
            self._view_state.should_exit = True
            if self._request_shutdown is not None:
                self._request_shutdown()
            return True

        if self.is_help_command(normalized):
            self._view_state.status_message = self.HELP_SUMMARY
            return False

        if cmd == "clear":
            self._request_journal.clear()
            self._ui_navigation.clear_requests()
            self._view_state.status_message = "Request list cleared."
            return False

        if cmd == "sites":
            with self._lock:
                top_sites = self._sites.most_common(5)
            if not top_sites:
                self._view_state.status_message = "No sites recorded yet."
            else:
                summary = ", ".join(f"{host} ({count})" for host, count in top_sites)
                self._view_state.status_message = f"Top sites: {summary}"
            return False

        if cmd == "filter":
            self._view_state.status_message = self._handle_filter_command(parts)
            return False

        if cmd == "find":
            self._view_state.status_message = self._handle_find_command(parts)
            return False

        if cmd == "export":
            self._view_state.status_message = self._handle_export_command(parts)
            return False

        if cmd == "session":
            self._view_state.status_message = self._handle_session_command(parts)
            return False

        command_result = self._command_service.execute(
            normalized,
            on_cache_toggle=self._trigger_cache_toggle_hook,
            on_schedule_policy_edit=self._schedule_policy_edit,
        )
        if command_result.handled:
            if command_result.updated_log_level is not None and self._on_log_level_change is not None:
                self._on_log_level_change(command_result.updated_log_level)
            self._view_state.status_message = command_result.status_message
            return False

        self._view_state.status_message = f"Unknown command: {command}"
        return False

    def is_help_command(self, command: str) -> bool:
        normalized = command.strip()
        if not normalized:
            return False
        return normalized.split()[0].lower() in {"help", "?"}

    def build_help_text(self) -> str:
        return (
            "Commands\n"
            "  help, ?                     Show this help dialog.\n"
            "  clear                       Clear the captured request list.\n"
            "  sites                       Show the busiest hosts.\n"
            "  loglevel <LEVEL>            Show or change the runtime log level.\n"
            "  filter ...                  Filter requests by host, method, status, or text.\n"
            "  find <text>                 Shortcut for full-text request filtering.\n"
            "  export <json|har> <path>    Export the current request list.\n"
            "  session <save|load> <path>  Save or load a captured session.\n"
            "  mitm ...                    Show or update MITM settings.\n"
            "  whitelist ...               Inspect or change the logging whitelist.\n"
            "  cache ...                   Inspect or toggle cache invalidation.\n"
            "  config ...                  Show, save, or reload runtime config.\n"
            "  policy ...                  Manage editor and static-response rules.\n"
            "  quit, exit, q               Stop the proxy.\n\n"
            "Navigation\n"
            "  Enter on a request          Open request detail.\n"
            "  Enter on a policy           Open policy editor (Policies tab).\n"
            "  Tab / Shift+Tab             Move forward or backward through panes.\n"
            "  Shift+S                     Toggle the sidebar; reselect Sites when visible.\n"
            "  Shift+P                     Show the sidebar and switch to Policies.\n"
            "  Shift+B                     Close sidebar/detail view (step back).\n"
            "  Shift+A                     Add the selected site to the whitelist.\n"
            "  Shift+U                     Remove the selected site from the whitelist.\n"
            "  Shift+D                     Disable the selected policy (Policies tab).\n"
            "  Shift+E                     Enable the selected policy (Policies tab).\n"
            "  Shift+I                     Edit the selected policy (Policies tab).\n"
            "  Shift+M                     Add and edit selected request as editor policy.\n"
            "  Shift+R                     Replay the selected request after editing.\n"
            "  Shift+X                     Remove the selected policy (Policies tab).\n"
            "  Shift+<letter>              Terminal sends uppercase character (e.g. Shift+M == M).\n"
            "  Esc / Enter                 Close this help dialog."
        )

    def _ordered_entries(self) -> list[LoggedExchange]:
        entries = list(self._request_journal.list_entries())
        entries.reverse()
        if self._request_filter.is_active():
            entries = [entry for entry in entries if self._request_filter.matches(entry)]
        return entries

    def _all_entries(self) -> list[LoggedExchange]:
        entries = list(self._request_journal.list_entries())
        entries.reverse()
        return entries

    def _handle_filter_command(self, parts: list[str]) -> str:
        if len(parts) == 1 or parts[1].lower() == "show":
            return f"Request filter: {self._request_filter.summary()}"

        action = parts[1].lower()
        value = " ".join(parts[2:]).strip()

        if action == "clear":
            self._request_filter.clear()
            self._reset_request_view_after_filter_change()
            return "Request filter cleared."

        if action == "host":
            if not value:
                return "Usage: filter host <hostname>|clear"
            self._request_filter.host = None if value.lower() == "clear" else value.lower()
            self._reset_request_view_after_filter_change()
            return f"Request filter: {self._request_filter.summary()}"

        if action == "method":
            if not value:
                return "Usage: filter method <HTTP method>|clear"
            self._request_filter.method = None if value.lower() == "clear" else value.upper()
            self._reset_request_view_after_filter_change()
            return f"Request filter: {self._request_filter.summary()}"

        if action == "status":
            if not value:
                return "Usage: filter status <HTTP status>|clear"
            if value.lower() == "clear":
                self._request_filter.status_code = None
            else:
                try:
                    self._request_filter.status_code = int(value)
                except ValueError:
                    return "Status filter must be an integer."
            self._reset_request_view_after_filter_change()
            return f"Request filter: {self._request_filter.summary()}"

        if action == "text":
            if not value:
                return "Usage: filter text <search text>|clear"
            self._request_filter.text = None if value.lower() == "clear" else value.lower()
            self._reset_request_view_after_filter_change()
            return f"Request filter: {self._request_filter.summary()}"

        return "Usage: filter [show|clear|host|method|status|text] ..."

    def _handle_find_command(self, parts: list[str]) -> str:
        query = " ".join(parts[1:]).strip()
        if not query:
            return "Usage: find <search text>|clear"
        self._request_filter.text = None if query.lower() == "clear" else query.lower()
        self._reset_request_view_after_filter_change()
        return f"Request filter: {self._request_filter.summary()}"

    def _handle_export_command(self, parts: list[str]) -> str:
        if len(parts) < 3:
            return "Usage: export <json|har> <path>"
        format_name = parts[1].lower()
        path = " ".join(parts[2:]).strip()
        if not path:
            return "Usage: export <json|har> <path>"
        try:
            destination = export_entries(
                list(self._request_journal.list_entries()),
                format_name=format_name,
                destination=path,
            )
        except ValueError as exc:
            return str(exc)
        except OSError as exc:
            return f"Export failed ({exc})."
        return f"Exported {format_name} snapshot to {destination}"

    def _handle_session_command(self, parts: list[str]) -> str:
        if len(parts) < 3:
            return "Usage: session <save|load> <path>"
        action = parts[1].lower()
        path = " ".join(parts[2:]).strip()
        if not path:
            return "Usage: session <save|load> <path>"
        if action == "save":
            try:
                destination = export_entries(
                    list(self._request_journal.list_entries()),
                    format_name="json",
                    destination=path,
                )
            except OSError as exc:
                return f"Session save failed ({exc})."
            return f"Saved session snapshot to {destination}"
        if action == "load":
            try:
                entries = load_entries_from_json(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return f"Session load failed ({exc})."
            self._request_journal.replace_entries(entries)
            self._reset_request_view_after_filter_change()
            return f"Loaded session snapshot from {path}"
        return "Usage: session <save|load> <path>"

    def _reset_request_view_after_filter_change(self) -> None:
        self._ui_navigation.reset_request_view(has_entries=bool(self._ordered_entries()))

    def _ordered_policy_items(self) -> list[tuple[str, str]]:
        rules = self._runtime_config.sorted_policy_rules()
        return [(rule.name, _format_policy_item(rule)) for rule in rules]

    def _selected_site(self) -> str | None:
        with self._lock:
            sites = [host for host, _count in self._sites.most_common()]
        return self._ui_navigation.selected_site(sites)

    def _selected_policy_name(self) -> str | None:
        policy_names = [name for name, _description in self._ordered_policy_items()]
        return self._ui_navigation.selected_policy_name(policy_names)

    def _ensure_policy_tab_active(self) -> bool:
        if self._ui_navigation.is_policy_tab_active():
            return True
        self._view_state.status_message = "Open Policies tab first (Shift+P)."
        return False

    def _schedule_policy_edit(self, name: str) -> None:
        self._policy_actions.schedule_edit(name)

    def _trigger_cache_toggle_hook(self) -> None:
        if self._on_cache_toggle is None:
            return
        try:
            self._on_cache_toggle()
        except Exception as exc:  # noqa: BLE001
            self._view_state.status_message = f"Failed to close active SSL tunnels: {exc}"

    def build_screen_model(self) -> "RuntimeScreenModel":
        with self._lock:
            site_counter = self._sites.copy()

        all_entries = self._all_entries()
        entries = self._ordered_entries()
        self._ui_navigation.sync_request_selection(entries)

        policy_items = [description for _name, description in self._ordered_policy_items()]
        self._ui_navigation.clamp_policy_cursor(len(policy_items))

        return build_runtime_screen_model(
            state=self._view_state,
            runtime_config=self._runtime_config,
            entries=entries,
            all_entry_count=len(all_entries),
            site_counter=site_counter,
            policy_items=policy_items,
            filter_summary=self._request_filter.summary(),
        )


def _format_policy_item(rule: PolicyRule) -> str:
    state = "ON" if rule.enabled else "OFF"
    method = ",".join(rule.match.methods or ("*",))
    target = rule.match.url_exact or rule.match.url_prefix or "*"
    if rule.action == "static_response" and rule.static_response is not None:
        return (
            f"{state:>3} p={rule.priority} {rule.name} | static {method} {target} -> {rule.static_response.status_code}"
        )
    return f"{state:>3} p={rule.priority} {rule.name} | {rule.action} {method} {target}"


def _entry_search_text(entry: LoggedExchange) -> str:
    parts = [
        entry.request.method,
        entry.request.path,
        entry.target_host or "",
        entry.client_ip,
        entry.request.body_preview,
    ]
    parts.extend(f"{name}: {value}" for name, value in entry.request.headers)
    if entry.response is not None:
        parts.append(str(entry.response.status_code))
        parts.append(entry.response.reason)
        parts.append(entry.response.body_preview)
        parts.extend(f"{name}: {value}" for name, value in entry.response.headers)
    return "\n".join(parts).lower()
