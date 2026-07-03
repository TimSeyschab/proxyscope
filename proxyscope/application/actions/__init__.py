from contextlib import nullcontext
from typing import Callable

from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.contracts import SuspendUI
from proxyscope.application.journal import LoggedExchange
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.response_edits import PendingResponseEdit, ResponseEditorResult, ResponseModifierService
from proxyscope.policies.models import OpenEditorAction, PolicyRule

PolicyEditor = Callable[[PolicyRule], tuple[bool, PolicyRule | None, str]]
ReplayRequest = Callable[..., tuple[bool, str]]
ResponseEditor = Callable[..., ResponseEditorResult]


class RuntimePolicyActionService:
    def __init__(
        self,
        policies: PolicyAdministrationService,
        configuration: RuntimeConfigurationService,
        *,
        policy_editor: PolicyEditor,
    ) -> None:
        self._policies = policies
        self._configuration = configuration
        self._policy_editor = policy_editor
        self._pending_edit_name: str | None = None

    @property
    def pending_edit_name(self) -> str | None:
        return self._pending_edit_name

    def schedule_edit(self, name: str) -> None:
        self._pending_edit_name = name

    def set_enabled(self, name: str | None, *, enabled: bool) -> str:
        if name is None:
            return "No policy selected."
        if self._policies.set_enabled(name, enabled=enabled):
            self._configuration.save()
            state = "enabled" if enabled else "disabled"
            return f"Policy {state}: {name}"
        return f"Policy not found: {name}"

    def remove(self, name: str | None) -> str:
        if name is None:
            return "No policy selected."
        if self._policies.remove_rule(name):
            self._configuration.save()
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
        return self.add_response_editor_policy_for_request(entry, suspend_ui=suspend_ui)

    def add_response_editor_policy_for_request(
        self,
        entry: LoggedExchange,
        *,
        suspend_ui: SuspendUI | None = None,
    ) -> str:
        target_url = entry_to_url(entry)
        if target_url is None:
            return "Cannot build URL from selected request."

        existing_names = {rule.name for rule in self._policies.list_rules()}
        try:
            normalized = self._policies.add_open_editor(
                target_url,
                method=entry.request.method,
            )
        except ValueError as exc:
            return str(exc)

        created_rule: PolicyRule | None = None
        for rule in reversed(self._policies.list_rules()):
            if rule.name in existing_names:
                continue
            if isinstance(rule.action, OpenEditorAction):
                created_rule = rule
                break

        if created_rule is None:
            self._configuration.save()
            return f"Added response editor policy: {normalized}"
        return self._edit_policy_rule(
            created_rule.name,
            created_rule,
            suspend_ui=suspend_ui,
            cleanup_on_failure=True,
        )

    def add_static_response_policy_for_request(
        self,
        entry: LoggedExchange,
        *,
        suspend_ui: SuspendUI | None = None,
    ) -> str:
        target_url = entry_to_url(entry)
        if target_url is None:
            return "Cannot build URL from selected request."
        if entry.response is None:
            return "Selected request has no response."
        if entry.response.body is None:
            return "Selected response body was not captured."
        if entry.response.body_size is not None and entry.response.body_size != len(entry.response.body):
            return "Selected response body was not fully captured."

        try:
            policy_name = self._add_static_response_policy(
                url=target_url,
                method=entry.request.method,
                status_code=entry.response.status_code,
                reason=entry.response.reason,
                headers=dict(entry.response.headers),
                body=entry.response.body,
            )
        except ValueError as exc:
            return str(exc)

        created_rule = self._policies.get_rule(policy_name)
        if created_rule is None:
            self._configuration.save()
            return f"Static response policy saved: {policy_name}"
        return self._edit_policy_rule(
            policy_name,
            created_rule,
            suspend_ui=suspend_ui,
            before_save=lambda: self._policies.remove_open_editor(target_url, method=entry.request.method),
            cleanup_on_failure=True,
        )

    def _edit_policy_by_name(self, name: str, *, suspend_ui: SuspendUI | None) -> str:
        try:
            rule = self._policies.get_rule(name)
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
        before_save: Callable[[], None] | None = None,
        cleanup_on_failure: bool = False,
    ) -> str:
        try:
            with _suspend_runtime_ui(suspend_ui):
                success, edited_rule, message = self._policy_editor(rule)
            if not success or edited_rule is None:
                if cleanup_on_failure:
                    self._policies.remove_rule(name)
                return message
            if self._policies.replace_rule(name, edited_rule):
                if before_save is not None:
                    before_save()
                self._configuration.save()
                return message
            return f"Policy not found: {name}"
        except Exception as exc:  # noqa: BLE001
            if cleanup_on_failure:
                self._policies.remove_rule(name)
            return f"Policy edit failed ({exc})."

    def _add_static_response_policy(
        self,
        *,
        url: str,
        method: str,
        status_code: int,
        reason: str,
        headers: dict[str, str],
        body: bytes,
    ) -> str:
        static_headers = _static_response_headers(headers, body=body)
        policy_name = self._policies.add_static_response(
            url=url,
            status_code=status_code,
            reason=reason,
            headers=static_headers,
            body=body,
            method=method,
            url_prefix=False,
        )
        return policy_name


class RuntimeReplayActionService:
    def __init__(self, *, proxy_base_url: str | None, replay_request: ReplayRequest) -> None:
        self._proxy_base_url = proxy_base_url
        self._replay_request = replay_request

    def replay(self, entry: LoggedExchange, *, suspend_ui: SuspendUI | None = None) -> str:
        request_url = entry_to_url(entry)
        if request_url is None:
            return "Cannot build URL from selected request."
        try:
            with _suspend_runtime_ui(suspend_ui):
                _success, message = self._replay_request(
                    entry,
                    request_url=request_url,
                    proxy_base_url=self._proxy_base_url,
                )
            return message
        except Exception as exc:  # noqa: BLE001
            return f"Replay failed ({exc})."


class RuntimeResponseEditActionService:
    def __init__(
        self,
        response_modifier: ResponseModifierService,
        policies: PolicyAdministrationService,
        configuration: RuntimeConfigurationService,
        *,
        response_editor: ResponseEditor,
    ) -> None:
        self._response_modifier = response_modifier
        self._policies = policies
        self._configuration = configuration
        self._response_editor = response_editor

    def process_pending_edit(self, *, suspend_ui: SuspendUI | None = None) -> str | None:
        pending = self._response_modifier.poll_pending_edit()
        if pending is None:
            return None
        try:
            with _suspend_runtime_ui(suspend_ui):
                result = self._response_editor(pending)
            if not result.success:
                pending.keep_original()
                return result.message
            if result.headers is None or result.body is None:
                return result.message
            try:
                policy_name = self._save_static_response_policy(
                    pending=pending,
                    headers=result.headers,
                    body=result.body,
                )
            except ValueError as exc:
                return f"{result.message}; static policy not saved ({exc})."
            self._configuration.save()
            return f"{result.message}; saved static policy {policy_name}."
        except Exception as exc:  # noqa: BLE001
            pending.keep_original()
            return f"Response edit failed ({exc}); kept original response."

    def _save_static_response_policy(
        self,
        *,
        pending: PendingResponseEdit,
        headers: dict[str, str],
        body: bytes,
    ) -> str:
        static_headers = _static_response_headers(headers, body=body)
        policy_name = self._policies.add_static_response(
            url=pending.request_url,
            status_code=pending.response.status_code,
            reason=pending.response.reason,
            headers=static_headers,
            body=body,
            method=pending.method,
            url_prefix=False,
        )
        self._policies.remove_open_editor(pending.request_url, method=pending.method)
        return policy_name


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


def _remove_header_case_insensitive(headers: dict[str, str], header_name: str) -> None:
    target = header_name.lower()
    for key in list(headers.keys()):
        if key.lower() == target:
            del headers[key]


def _static_response_headers(headers: dict[str, str], *, body: bytes) -> dict[str, str]:
    static_headers = dict(headers)
    _remove_header_case_insensitive(static_headers, "Transfer-Encoding")
    static_headers["Content-Length"] = str(len(body))
    return static_headers
