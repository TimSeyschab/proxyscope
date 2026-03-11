from collections import Counter
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
import json
import logging
from threading import Lock
from typing import Callable

from proxyscope.app.config.runtime import PolicyRule, RuntimeConfig
from proxyscope.app.editing.policy import edit_policy_rule_with_external_editor
from proxyscope.app.runtime.commands import RuntimeCommandService
from proxyscope.app.runtime.journal import LoggedExchange, RequestJournal
from proxyscope.app.runtime.replay import edit_and_resend_logged_request
from proxyscope.app.runtime.exporting import export_entries, load_entries_from_json
from proxyscope.app.runtime.ui_models import RuntimeScreenModel
from proxyscope.app.runtime.ui_presenter import build_runtime_screen_model
from proxyscope.app.runtime.ui_state import RuntimeUIViewState
from proxyscope.app.editing.response import edit_pending_response_with_external_editor
from proxyscope.app.editing.modifier import PendingResponseEdit, ResponseModifierService


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


class RuntimeCLI(logging.Handler):
    def __init__(
        self,
        *,
        runtime_config: RuntimeConfig,
        request_journal: RequestJournal,
        response_modifier: ResponseModifierService,
        proxy_base_url: str | None = None,
    ) -> None:
        super().__init__(level=logging.INFO)
        self._runtime_config = runtime_config
        self._request_journal = request_journal
        self._response_modifier = response_modifier
        self._proxy_base_url = proxy_base_url
        self._sites: Counter[str] = Counter()
        self._lock = Lock()
        self._shutdown_server: Callable[[], None] | None = None
        self._on_cache_toggle: Callable[[], None] | None = None
        self._request_filter = RequestFilterState()
        self._view_state = RuntimeUIViewState()
        self._command_service = RuntimeCommandService(runtime_config=self._runtime_config)

    @property
    def _command_buffer(self) -> str:
        return self._view_state.command_buffer

    @_command_buffer.setter
    def _command_buffer(self, value: str) -> None:
        self._view_state.command_buffer = value

    @property
    def _active_pane(self) -> str:
        return self._view_state.active_pane

    @_active_pane.setter
    def _active_pane(self, value: str) -> None:
        self._view_state.active_pane = value  # type: ignore[assignment]

    @property
    def _aux_tab_key(self) -> str:
        return self._view_state.aux_tab_key

    @_aux_tab_key.setter
    def _aux_tab_key(self, value: str) -> None:
        self._view_state.aux_tab_key = value

    @property
    def _main_mode(self) -> str:
        return self._view_state.main_mode

    @_main_mode.setter
    def _main_mode(self, value: str) -> None:
        self._view_state.main_mode = value  # type: ignore[assignment]

    @property
    def _status_message(self) -> str:
        return self._view_state.status_message

    @_status_message.setter
    def _status_message(self, value: str) -> None:
        self._view_state.status_message = value

    @property
    def _pending_policy_edit_name(self) -> str | None:
        return self._view_state.pending_policy_edit_name

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        line = self.format(record)
        with self._lock:
            self._view_state.status_message = line

    def on_site_visit(self, host: str) -> None:
        with self._lock:
            self._sites[host] += 1

    def run(
        self,
        *,
        shutdown_server: Callable[[], None],
        on_cache_toggle: Callable[[], None] | None = None,
    ) -> None:
        self._shutdown_server = shutdown_server
        self._on_cache_toggle = on_cache_toggle
        from proxyscope.app.runtime.textual_ui import RuntimeTextualApp

        RuntimeTextualApp(self).run()

    def execute_command(self, command: str) -> bool:
        normalized = command.strip()
        if not normalized:
            return False

        parts = normalized.split()
        cmd = parts[0].lower()

        if cmd in {"q", "quit", "exit"}:
            self._view_state.status_message = "Shutting down server..."
            self._view_state.should_exit = True
            if self._shutdown_server is not None:
                self._shutdown_server()
            return True

        if cmd == "help":
            self._view_state.status_message = (
                "Commands: help | clear | sites | loglevel <LEVEL> | "
                "filter [show|clear|host|method|status|text] ... | find <text>|find clear | "
                "export <json|har> <path> | "
                "session <save|load> <path> | "
                "mitm [show|on|off|certs-dir <path>] | "
                "whitelist [add|remove|clear|show] ... | cache [show|on|off|toggle] | "
                "config [show|save [path]|reload] | "
                "policy [show|add-editor|add-editor-prefix|remove-editor|clear-editor|"
                "add-static|add-static-prefix|set-priority|edit|remove|enable|disable] ... | "
                "Hotkeys (Shift): A/B/D/E/I/M/P/R/S/T/V/X | quit"
            )
            return False

        if cmd == "clear":
            self._request_journal.clear()
            self._view_state.request_cursor = 0
            self._view_state.main_mode = "requests"
            self._view_state.active_pane = "requests"
            self._view_state.aux_tab_key = "sites"
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
            if command_result.updated_log_level is not None:
                logging.getLogger().setLevel(command_result.updated_log_level)
            self._view_state.status_message = command_result.status_message
            return False

        self._view_state.status_message = f"Unknown command: {command}"
        return False

    def _go_back(self) -> None:
        if not self._view_state.go_back():
            self._view_state.status_message = "Nothing to close."

    def _focus_aux_tab(self, tab_key: str) -> None:
        self._view_state.focus_aux_tab(tab_key)

    def _toggle_aux_visibility(self) -> None:
        self._view_state.toggle_aux_visibility()

    def _toggle_detail_tab(self) -> None:
        self._view_state.detail_tab = "response" if self._view_state.detail_tab == "request" else "request"

    def _open_selected_request_detail(self) -> None:
        if not self._ordered_entries():
            self._view_state.status_message = "No requests available."
            return
        self._view_state.open_selected_request_detail()

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
        self._view_state.reset_request_view()
        if not self._ordered_entries():
            self._view_state.switch_to_request_list_mode()

    def _ordered_policy_items(self) -> list[tuple[str, str]]:
        rules = self._runtime_config.policy_rules()
        return [(rule.name, _format_policy_item(rule)) for rule in rules]

    def _selected_site(self) -> str | None:
        with self._lock:
            sites = [host for host, _count in self._sites.most_common()]
            if not sites:
                return None
            if self._view_state.site_cursor >= len(sites):
                self._view_state.site_cursor = max(0, len(sites) - 1)
            return sites[self._view_state.site_cursor]

    def _selected_policy_name(self) -> str | None:
        policies = self._ordered_policy_items()
        if not policies:
            return None
        if self._view_state.policy_cursor >= len(policies):
            self._view_state.policy_cursor = max(0, len(policies) - 1)
        return policies[self._view_state.policy_cursor][0]

    def _add_selected_site_to_whitelist(self) -> None:
        selected = self._selected_site()
        if not selected:
            self._view_state.status_message = "No site selected."
            return
        added = self._runtime_config.add_whitelist_entry(selected)
        self._view_state.status_message = f"Added selected site to whitelist: {added}"

    def _remove_selected_site_from_whitelist(self) -> None:
        selected = self._selected_site()
        if not selected:
            self._view_state.status_message = "No site selected."
            return
        removed = self._runtime_config.remove_whitelist_entry(selected)
        if removed:
            self._view_state.status_message = f"Removed selected site from whitelist: {selected}"
        else:
            self._view_state.status_message = f"Selected site not in whitelist: {selected}"

    def _enable_selected_policy(self) -> None:
        name = self._selected_policy_name()
        if name is None:
            self._view_state.status_message = "No policy selected."
            return
        if self._runtime_config.set_policy_rule_enabled(name, enabled=True):
            self._view_state.status_message = f"Policy enabled: {name}"
        else:
            self._view_state.status_message = f"Policy not found: {name}"

    def _disable_selected_policy(self) -> None:
        name = self._selected_policy_name()
        if name is None:
            self._view_state.status_message = "No policy selected."
            return
        if self._runtime_config.set_policy_rule_enabled(name, enabled=False):
            self._view_state.status_message = f"Policy disabled: {name}"
        else:
            self._view_state.status_message = f"Policy not found: {name}"

    def _remove_selected_policy(self) -> None:
        name = self._selected_policy_name()
        if name is None:
            self._view_state.status_message = "No policy selected."
            return
        if self._runtime_config.remove_policy_rule(name):
            self._view_state.status_message = f"Policy removed: {name}"
        else:
            self._view_state.status_message = f"Policy not found: {name}"

    def _schedule_policy_edit(self, name: str) -> None:
        self._view_state.pending_policy_edit_name = name

    def _edit_selected_policy(
        self,
        *,
        suspend_ui: Callable[[], AbstractContextManager[None]] | None = None,
    ) -> None:
        name = self._selected_policy_name()
        if name is None:
            self._view_state.status_message = "No policy selected."
            return
        try:
            rule = self._runtime_config.get_policy_rule(name)
        except ValueError as exc:
            self._view_state.status_message = str(exc)
            return
        if rule is None:
            self._view_state.status_message = f"Policy not found: {name}"
            return

        self._edit_policy_rule_interactive(name, rule, suspend_ui=suspend_ui)

    def _process_pending_policy_edit(
        self,
        *,
        suspend_ui: Callable[[], AbstractContextManager[None]] | None = None,
    ) -> None:
        pending_name = self._view_state.pending_policy_edit_name
        if pending_name is None:
            return
        self._view_state.pending_policy_edit_name = None
        try:
            rule = self._runtime_config.get_policy_rule(pending_name)
        except ValueError as exc:
            self._view_state.status_message = str(exc)
            return
        if rule is None:
            self._view_state.status_message = f"Policy not found: {pending_name}"
            return
        self._edit_policy_rule_interactive(pending_name, rule, suspend_ui=suspend_ui)

    def _edit_policy_rule_interactive(
        self,
        name: str,
        rule: PolicyRule,
        *,
        suspend_ui: Callable[[], AbstractContextManager[None]] | None = None,
    ) -> None:
        try:
            with _suspend_runtime_ui(suspend_ui=suspend_ui):
                success, edited_rule, message = edit_policy_rule_with_external_editor(rule)
            if not success or edited_rule is None:
                self._view_state.status_message = message
                return
            if self._runtime_config.replace_policy_rule(name, edited_rule):
                self._view_state.status_message = message
            else:
                self._view_state.status_message = f"Policy not found: {name}"
        except Exception as exc:  # noqa: BLE001
            self._view_state.status_message = f"Policy edit failed ({exc})."

    def _add_selected_request_to_modify_whitelist(self) -> None:
        entries = self._ordered_entries()
        if not entries:
            self._view_state.status_message = "No request selected."
            return
        selected = entries[self._view_state.request_cursor]
        target_url = _entry_to_url(selected)
        if target_url is None:
            self._view_state.status_message = "Cannot build URL from selected request."
            return
        normalized = self._runtime_config.add_open_editor_policy(
            target_url,
            method=selected.request.method,
        )
        self._view_state.status_message = f"Added editor policy: {normalized}"

    def _edit_and_resend_selected_request_with_ui_suspend(
        self,
        *,
        suspend_ui: Callable[[], AbstractContextManager[None]] | None = None,
    ) -> None:
        entries = self._ordered_entries()
        if not entries:
            self._view_state.status_message = "No request selected."
            return
        selected = entries[self._view_state.request_cursor]
        request_url = _entry_to_url(selected)
        if request_url is None:
            self._view_state.status_message = "Cannot build URL from selected request."
            return

        try:
            with _suspend_runtime_ui(suspend_ui=suspend_ui):
                success, message = edit_and_resend_logged_request(
                    selected,
                    request_url=request_url,
                    proxy_base_url=self._proxy_base_url,
                )
            self._view_state.status_message = message
            if not success:
                return
        except Exception as exc:  # noqa: BLE001
            self._view_state.status_message = f"Replay failed ({exc})."

    def _process_pending_editor(
        self,
        *,
        suspend_ui: Callable[[], AbstractContextManager[None]] | None = None,
    ) -> None:
        pending = self._response_modifier.poll_pending_edit()
        if pending is None:
            return
        self._open_editor_for_pending(pending, suspend_ui=suspend_ui)

    def _open_editor_for_pending(
        self,
        pending: PendingResponseEdit,
        *,
        suspend_ui: Callable[[], AbstractContextManager[None]] | None = None,
    ) -> None:
        try:
            with _suspend_runtime_ui(suspend_ui=suspend_ui):
                success, message = edit_pending_response_with_external_editor(pending)
            self._view_state.status_message = message
            if not success:
                pending.keep_original()
        except Exception as exc:  # noqa: BLE001
            pending.keep_original()
            self._view_state.status_message = f"Response edit failed ({exc}); kept original response."

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
        if self._view_state.request_cursor >= len(entries):
            self._view_state.request_cursor = max(0, len(entries) - 1)

        policy_items = [description for _name, description in self._ordered_policy_items()]
        if self._view_state.policy_cursor >= len(policy_items):
            self._view_state.policy_cursor = max(0, len(policy_items) - 1)

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
            f"{state:>3} p={rule.priority} {rule.name} | "
            f"static {method} {target} -> {rule.static_response.status_code}"
        )
    return f"{state:>3} p={rule.priority} {rule.name} | {rule.action} {method} {target}"


def _entry_to_url(entry: LoggedExchange) -> str | None:
    host = entry.target_host
    if not host:
        return None
    path = entry.request.path
    if path.startswith("http://") or path.startswith("https://"):
        return path
    normalized_path = path if path.startswith("/") else f"/{path}"
    scheme = "https" if entry.protocol.startswith("https") else "http"
    if entry.target_port is None:
        return f"{scheme}://{host}{normalized_path}"
    default_port = 443 if scheme == "https" else 80
    if entry.target_port == default_port:
        return f"{scheme}://{host}{normalized_path}"
    return f"{scheme}://{host}:{entry.target_port}{normalized_path}"


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


def _suspend_runtime_ui(
    *,
    suspend_ui: Callable[[], AbstractContextManager[None]] | None = None,
) -> AbstractContextManager[None]:
    if suspend_ui is not None:
        return suspend_ui()
    return nullcontext()
