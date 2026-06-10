from contextlib import nullcontext

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.editing.modifier import ResponseModifierService
from proxyscope.app.editing.policy import edit_policy_rule_with_external_editor
from proxyscope.app.editing.response import edit_pending_response_with_external_editor
from proxyscope.app.runtime.journal import LoggedExchange
from proxyscope.app.runtime.replay import edit_and_resend_logged_request
from proxyscope.app.runtime.ui_controller import SuspendUI
from proxyscope.policies.models import OpenEditorAction, PolicyRule


class RuntimePolicyActionService:
    def __init__(self, runtime_config: RuntimeConfig) -> None:
        self._runtime_config = runtime_config
        self._pending_edit_name: str | None = None

    @property
    def pending_edit_name(self) -> str | None:
        return self._pending_edit_name

    def schedule_edit(self, name: str) -> None:
        self._pending_edit_name = name

    def set_enabled(self, name: str | None, *, enabled: bool) -> str:
        if name is None:
            return "No policy selected."
        if self._runtime_config.set_policy_rule_enabled(name, enabled=enabled):
            state = "enabled" if enabled else "disabled"
            return f"Policy {state}: {name}"
        return f"Policy not found: {name}"

    def remove(self, name: str | None) -> str:
        if name is None:
            return "No policy selected."
        if self._runtime_config.remove_policy_rule(name):
            return f"Policy removed: {name}"
        return f"Policy not found: {name}"

    def edit(self, name: str | None, *, suspend_ui: SuspendUI | None = None) -> str:
        if name is None:
            return "No policy selected."
        return self._edit_policy_by_name(name, suspend_ui=suspend_ui)

    def process_pending_edit(self, *, suspend_ui: SuspendUI | None = None) -> str | None:
        pending_name = self._pending_edit_name
        if pending_name is None:
            return None
        self._pending_edit_name = None
        return self._edit_policy_by_name(pending_name, suspend_ui=suspend_ui)

    def add_request_to_editor_policy(
        self,
        entry: LoggedExchange,
        *,
        suspend_ui: SuspendUI | None = None,
    ) -> str:
        target_url = entry_to_url(entry)
        if target_url is None:
            return "Cannot build URL from selected request."

        existing_names = {rule.name for rule in self._runtime_config.policy_rules()}
        try:
            normalized = self._runtime_config.add_open_editor_policy(
                target_url,
                method=entry.request.method,
            )
        except ValueError as exc:
            return str(exc)

        created_rule: PolicyRule | None = None
        for rule in reversed(self._runtime_config.policy_rules()):
            if rule.name in existing_names:
                continue
            if isinstance(rule.action, OpenEditorAction):
                created_rule = rule
                break

        if created_rule is None:
            return f"Added editor policy: {normalized}"
        return self._edit_policy_rule(created_rule.name, created_rule, suspend_ui=suspend_ui)

    def _edit_policy_by_name(self, name: str, *, suspend_ui: SuspendUI | None) -> str:
        try:
            rule = self._runtime_config.get_policy_rule(name)
        except ValueError as exc:
            return str(exc)
        if rule is None:
            return f"Policy not found: {name}"
        return self._edit_policy_rule(name, rule, suspend_ui=suspend_ui)

    def _edit_policy_rule(
        self,
        name: str,
        rule: PolicyRule,
        *,
        suspend_ui: SuspendUI | None,
    ) -> str:
        try:
            with _suspend_runtime_ui(suspend_ui):
                success, edited_rule, message = edit_policy_rule_with_external_editor(rule)
            if not success or edited_rule is None:
                return message
            if self._runtime_config.replace_policy_rule(name, edited_rule):
                return message
            return f"Policy not found: {name}"
        except Exception as exc:  # noqa: BLE001
            return f"Policy edit failed ({exc})."


class RuntimeReplayActionService:
    def __init__(self, *, proxy_base_url: str | None) -> None:
        self._proxy_base_url = proxy_base_url

    def replay(self, entry: LoggedExchange, *, suspend_ui: SuspendUI | None = None) -> str:
        request_url = entry_to_url(entry)
        if request_url is None:
            return "Cannot build URL from selected request."
        try:
            with _suspend_runtime_ui(suspend_ui):
                _success, message = edit_and_resend_logged_request(
                    entry,
                    request_url=request_url,
                    proxy_base_url=self._proxy_base_url,
                )
            return message
        except Exception as exc:  # noqa: BLE001
            return f"Replay failed ({exc})."


class RuntimeResponseEditActionService:
    def __init__(self, response_modifier: ResponseModifierService, runtime_config: RuntimeConfig) -> None:
        self._response_modifier = response_modifier
        self._runtime_config = runtime_config

    def process_pending_edit(self, *, suspend_ui: SuspendUI | None = None) -> str | None:
        pending = self._response_modifier.poll_pending_edit()
        if pending is None:
            return None
        try:
            with _suspend_runtime_ui(suspend_ui):
                success, message = edit_pending_response_with_external_editor(
                    pending,
                    runtime_config=self._runtime_config,
                )
            if not success:
                pending.keep_original()
            return message
        except Exception as exc:  # noqa: BLE001
            pending.keep_original()
            return f"Response edit failed ({exc}); kept original response."


def entry_to_url(entry: LoggedExchange) -> str | None:
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


def _suspend_runtime_ui(suspend_ui: SuspendUI | None):
    if suspend_ui is not None:
        return suspend_ui()
    return nullcontext()
