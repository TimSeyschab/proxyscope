from typing import Callable

from proxyscope.application.commands.runtime_result import CommandExecutionResult
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.policies.matching import normalize_http_method, normalize_policy_url

MIN_HTTP_STATUS_CODE = 100
MAX_HTTP_STATUS_CODE = 599
DEFAULT_POLICY_METHOD = "GET"
DEFAULT_STATIC_RESPONSE_STATUS_CODE = 200
DEFAULT_STATIC_RESPONSE_CONTENT_TYPE = "text/plain; charset=utf-8"
POLICY_SHOW_PREVIEW_LIMIT = 3

KNOWN_HTTP_METHODS = frozenset(
    {
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "HEAD",
        "OPTIONS",
        "TRACE",
        "CONNECT",
    }
)

HTTP_REASON_PHRASES = {
    200: "OK",
    201: "Created",
    202: "Accepted",
    204: "No Content",
    301: "Moved Permanently",
    302: "Found",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    418: "I'm a teapot",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


class PolicyCommandHandler:
    def __init__(
        self,
        *,
        policies: PolicyAdministrationService,
        configuration: RuntimeConfigurationService,
    ) -> None:
        self._policies = policies
        self._configuration = configuration

    def execute(
        self,
        parts: list[str],
        *,
        on_schedule_policy_edit: Callable[[str], None],
    ) -> CommandExecutionResult:
        if len(parts) == 1 or parts[1].lower() == "show":
            entries = self._policies.descriptions()
            if not entries:
                return CommandExecutionResult(handled=True, status_message="No policy rules configured.")
            preview = ", ".join(entries[:POLICY_SHOW_PREVIEW_LIMIT])
            if len(entries) > POLICY_SHOW_PREVIEW_LIMIT:
                preview += ", ..."
            return CommandExecutionResult(
                handled=True,
                status_message=f"Policies ({len(entries)}): {preview}",
            )

        action = parts[1].lower()
        if action in {"add-static", "add-static-prefix"}:
            return self._add_static_policy(parts, url_prefix=(action == "add-static-prefix"))
        if action in {"add-editor", "add-editor-prefix"}:
            return self._add_editor_policy(parts, url_prefix=(action == "add-editor-prefix"))
        if action == "remove-editor":
            return self._remove_editor_policy(parts)
        if action == "clear-editor":
            self._policies.clear_open_editor()
            self._configuration.save()
            return CommandExecutionResult(
                handled=True,
                status_message="Cleared all open-editor policies.",
            )
        if action == "remove":
            return self._remove_policy(parts)
        if action in {"enable", "disable"}:
            return self._set_policy_enabled(parts, enabled=(action == "enable"))
        if action == "set-priority":
            return self._set_policy_priority(parts)
        if action == "edit":
            return self._edit_policy(parts, on_schedule_policy_edit=on_schedule_policy_edit)

        return CommandExecutionResult(
            handled=True,
            status_message=(
                "Usage: policy [show|add-editor|add-editor-prefix|remove-editor|clear-editor|"
                "add-static|add-static-prefix|set-priority|edit|remove|enable|disable] ..."
            ),
        )

    def _add_static_policy(self, parts: list[str], *, url_prefix: bool) -> CommandExecutionResult:
        parsed = _parse_add_static_policy_arguments(parts[2:])
        if parsed is None:
            return CommandExecutionResult(
                handled=True,
                status_message="Usage: policy add-static[ -prefix ] [METHOD] <url> [status] [content-type] [body...]",
            )
        method, url, status_code, content_type, body_text = parsed
        if status_code < MIN_HTTP_STATUS_CODE or status_code > MAX_HTTP_STATUS_CODE:
            return CommandExecutionResult(
                handled=True,
                status_message=f"Status code must be in range {MIN_HTTP_STATUS_CODE}..{MAX_HTTP_STATUS_CODE}.",
            )
        headers = {"Content-Type": content_type}
        rule_name = self._policies.add_static_response(
            url=url,
            status_code=status_code,
            reason=_default_reason_phrase(status_code),
            headers=headers,
            body=body_text.encode("utf-8"),
            method=method,
            url_prefix=url_prefix,
        )
        self._configuration.save()
        return CommandExecutionResult(handled=True, status_message=f"Added static policy: {rule_name}")

    def _add_editor_policy(self, parts: list[str], *, url_prefix: bool) -> CommandExecutionResult:
        method, value = _parse_modify_method_and_url(parts[2:])
        if not value:
            return CommandExecutionResult(
                handled=True,
                status_message="Usage: policy add-editor[ -prefix ] [METHOD] <url>",
            )
        try:
            normalized = self._policies.add_open_editor(
                value,
                method=method or DEFAULT_POLICY_METHOD,
                url_prefix=url_prefix,
            )
            self._configuration.save()
        except ValueError as exc:
            return CommandExecutionResult(handled=True, status_message=str(exc))
        return CommandExecutionResult(handled=True, status_message=f"Added editor policy: {normalized}")

    def _remove_editor_policy(self, parts: list[str]) -> CommandExecutionResult:
        method, value = _parse_modify_method_and_url(parts[2:])
        if not value:
            return CommandExecutionResult(
                handled=True,
                status_message="Usage: policy remove-editor [METHOD] <url>",
            )
        try:
            removed = self._policies.remove_open_editor(value, method=method)
            if removed:
                self._configuration.save()
            normalized = normalize_policy_url(value)
            method_label = normalize_http_method(method) if method is not None else "*"
        except ValueError as exc:
            return CommandExecutionResult(handled=True, status_message=str(exc))
        if removed:
            return CommandExecutionResult(
                handled=True,
                status_message=f"Removed editor policy: {method_label} {normalized}",
            )
        return CommandExecutionResult(
            handled=True,
            status_message=f"Editor policy not found: {method_label} {normalized}",
        )

    def _remove_policy(self, parts: list[str]) -> CommandExecutionResult:
        name = " ".join(parts[2:]).strip()
        if not name:
            return CommandExecutionResult(handled=True, status_message="Usage: policy remove <name>")
        try:
            removed = self._policies.remove_rule(name)
            if removed:
                self._configuration.save()
        except ValueError as exc:
            return CommandExecutionResult(handled=True, status_message=str(exc))
        if removed:
            return CommandExecutionResult(handled=True, status_message=f"Removed policy: {name}")
        return CommandExecutionResult(handled=True, status_message=f"Policy not found: {name}")

    def _set_policy_enabled(self, parts: list[str], *, enabled: bool) -> CommandExecutionResult:
        action = "enable" if enabled else "disable"
        name = " ".join(parts[2:]).strip()
        if not name:
            return CommandExecutionResult(
                handled=True,
                status_message=f"Usage: policy {action} <name>",
            )
        try:
            changed = self._policies.set_enabled(name, enabled=enabled)
            if changed:
                self._configuration.save()
        except ValueError as exc:
            return CommandExecutionResult(handled=True, status_message=str(exc))
        if changed:
            state = "enabled" if enabled else "disabled"
            return CommandExecutionResult(handled=True, status_message=f"Policy {state}: {name}")
        return CommandExecutionResult(handled=True, status_message=f"Policy not found: {name}")

    def _set_policy_priority(self, parts: list[str]) -> CommandExecutionResult:
        if len(parts) < 4:
            return CommandExecutionResult(
                handled=True,
                status_message="Usage: policy set-priority <name> <integer>",
            )
        name = " ".join(parts[2:-1]).strip()
        raw_priority = parts[-1]
        if not name:
            return CommandExecutionResult(
                handled=True,
                status_message="Usage: policy set-priority <name> <integer>",
            )
        try:
            priority = int(raw_priority)
        except ValueError:
            return CommandExecutionResult(
                handled=True,
                status_message="Priority must be an integer.",
            )
        try:
            changed = self._policies.set_priority(name, priority=priority)
            if changed:
                self._configuration.save()
        except ValueError as exc:
            return CommandExecutionResult(handled=True, status_message=str(exc))
        if changed:
            return CommandExecutionResult(
                handled=True,
                status_message=f"Policy priority set: {name} -> {priority}",
            )
        return CommandExecutionResult(handled=True, status_message=f"Policy not found: {name}")

    def _edit_policy(
        self,
        parts: list[str],
        *,
        on_schedule_policy_edit: Callable[[str], None],
    ) -> CommandExecutionResult:
        name = " ".join(parts[2:]).strip()
        if not name:
            return CommandExecutionResult(handled=True, status_message="Usage: policy edit <name>")
        try:
            rule = self._policies.get_rule(name)
        except ValueError as exc:
            return CommandExecutionResult(handled=True, status_message=str(exc))
        if rule is None:
            return CommandExecutionResult(handled=True, status_message=f"Policy not found: {name}")
        on_schedule_policy_edit(name)
        return CommandExecutionResult(handled=True, status_message=f"Opening policy editor: {name}")


def _parse_modify_method_and_url(tokens: list[str]) -> tuple[str | None, str]:
    if not tokens:
        return None, ""
    if len(tokens) == 1:
        return None, tokens[0]
    first = tokens[0].strip()
    if not first:
        return None, " ".join(tokens[1:]).strip()
    if first.upper() in KNOWN_HTTP_METHODS:
        return first.upper(), " ".join(tokens[1:]).strip()
    return None, " ".join(tokens).strip()


def _parse_add_static_policy_arguments(tokens: list[str]) -> tuple[str, str, int, str, str] | None:
    method, value = _parse_modify_method_and_url(tokens)
    method_value = method or DEFAULT_POLICY_METHOD
    if not value:
        return None

    parsed_tokens = value.split()
    if not parsed_tokens:
        return None
    url = parsed_tokens[0]
    status_code = DEFAULT_STATIC_RESPONSE_STATUS_CODE
    content_type = DEFAULT_STATIC_RESPONSE_CONTENT_TYPE
    body_text = ""

    offset = 1
    if len(parsed_tokens) > offset and parsed_tokens[offset].isdigit():
        status_code = int(parsed_tokens[offset])
        offset += 1
    if len(parsed_tokens) > offset:
        content_type = parsed_tokens[offset]
        offset += 1
    if len(parsed_tokens) > offset:
        body_text = " ".join(parsed_tokens[offset:])

    return method_value, url, status_code, content_type, body_text


def _default_reason_phrase(status_code: int) -> str:
    return HTTP_REASON_PHRASES.get(status_code, "OK")
