import json
from dataclasses import dataclass
from typing import Callable

from proxyscope.app.config.runtime import RuntimeConfig
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


@dataclass(frozen=True)
class CommandExecutionResult:
    handled: bool
    status_message: str = ""
    updated_log_level: int | None = None


class RuntimeCommandService:
    """
    Parse and execute runtime commands that mutate shared runtime configuration.
    """

    def __init__(self, *, runtime_config: RuntimeConfig) -> None:
        self._runtime_config = runtime_config

    def execute(
        self,
        command: str,
        *,
        on_cache_toggle: Callable[[], None] | None,
        on_schedule_policy_edit: Callable[[str], None],
    ) -> CommandExecutionResult:
        normalized = command.strip()
        if not normalized:
            return CommandExecutionResult(handled=False)

        parts = normalized.split()
        cmd = parts[0].lower()

        if cmd == "loglevel":
            return self._handle_loglevel(parts)
        if cmd in {"whitelist", "wl"}:
            return self._handle_whitelist(parts)
        if cmd == "cache":
            return self._handle_cache(parts, on_cache_toggle=on_cache_toggle)
        if cmd == "mitm":
            return self._handle_mitm(parts)
        if cmd == "config":
            return self._handle_config(parts, on_cache_toggle=on_cache_toggle)
        if cmd in {"policy", "pol"}:
            return self._handle_policy(parts, on_schedule_policy_edit=on_schedule_policy_edit)
        return CommandExecutionResult(handled=False)

    def _handle_loglevel(self, parts: list[str]) -> CommandExecutionResult:
        if len(parts) == 1:
            return CommandExecutionResult(
                handled=True,
                status_message=f"Current log level: {self._runtime_config.log_level_name()}",
            )
        try:
            new_level = self._runtime_config.set_log_level(parts[1])
        except ValueError as exc:
            return CommandExecutionResult(handled=True, status_message=str(exc))
        return CommandExecutionResult(
            handled=True,
            status_message=f"Log level set to {self._runtime_config.log_level_name()}",
            updated_log_level=new_level,
        )

    def _handle_whitelist(self, parts: list[str]) -> CommandExecutionResult:
        if len(parts) == 1 or parts[1].lower() == "show":
            entries = self._runtime_config.whitelist_entries()
            if not entries:
                return CommandExecutionResult(
                    handled=True,
                    status_message="Whitelist is empty (logging enabled for all hosts).",
                )
            return CommandExecutionResult(
                handled=True,
                status_message="Whitelist: " + ", ".join(entries),
            )

        action = parts[1].lower()
        value = " ".join(parts[2:]).strip()

        if action == "add":
            if not value:
                return CommandExecutionResult(
                    handled=True,
                    status_message="Usage: whitelist add <host-or-url>",
                )
            try:
                added = self._runtime_config.add_whitelist_entry(value)
            except ValueError as exc:
                return CommandExecutionResult(handled=True, status_message=str(exc))
            return CommandExecutionResult(handled=True, status_message=f"Added to whitelist: {added}")

        if action == "remove":
            if not value:
                return CommandExecutionResult(
                    handled=True,
                    status_message="Usage: whitelist remove <host-or-url>",
                )
            try:
                removed = self._runtime_config.remove_whitelist_entry(value)
            except ValueError as exc:
                return CommandExecutionResult(handled=True, status_message=str(exc))
            if removed:
                return CommandExecutionResult(
                    handled=True,
                    status_message=f"Removed from whitelist: {value}",
                )
            return CommandExecutionResult(handled=True, status_message=f"Not in whitelist: {value}")

        if action == "clear":
            self._runtime_config.clear_whitelist()
            return CommandExecutionResult(
                handled=True,
                status_message="Whitelist cleared (logging enabled for all hosts).",
            )

        return CommandExecutionResult(
            handled=True,
            status_message="Usage: whitelist [show|add|remove|clear] ...",
        )

    def _handle_cache(
        self,
        parts: list[str],
        *,
        on_cache_toggle: Callable[[], None] | None,
    ) -> CommandExecutionResult:
        if len(parts) == 1 or parts[1].lower() == "show":
            enabled = self._runtime_config.cache_invalidation_enabled
            state = "on" if enabled else "off"
            return CommandExecutionResult(handled=True, status_message=f"Cache invalidation: {state}")

        action = parts[1].lower()
        if action == "on":
            self._runtime_config.set_cache_invalidation_enabled(True)
            _trigger_callback(on_cache_toggle)
            return CommandExecutionResult(handled=True, status_message="Cache invalidation enabled.")
        if action == "off":
            self._runtime_config.set_cache_invalidation_enabled(False)
            _trigger_callback(on_cache_toggle)
            return CommandExecutionResult(handled=True, status_message="Cache invalidation disabled.")
        if action == "toggle":
            enabled = self._runtime_config.toggle_cache_invalidation()
            _trigger_callback(on_cache_toggle)
            state = "enabled" if enabled else "disabled"
            return CommandExecutionResult(handled=True, status_message=f"Cache invalidation {state}.")

        return CommandExecutionResult(
            handled=True,
            status_message="Usage: cache [show|on|off|toggle]",
        )

    def _handle_policy(
        self,
        parts: list[str],
        *,
        on_schedule_policy_edit: Callable[[str], None],
    ) -> CommandExecutionResult:
        if len(parts) == 1 or parts[1].lower() == "show":
            entries = self._runtime_config.policy_descriptions()
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
            parsed = _parse_add_static_policy_arguments(parts[2:])
            if parsed is None:
                return CommandExecutionResult(
                    handled=True,
                    status_message=(
                        "Usage: policy add-static[ -prefix ] [METHOD] <url> [status] [content-type] [body...]"
                    ),
                )
            method, url, status_code, content_type, body_text = parsed
            if status_code < MIN_HTTP_STATUS_CODE or status_code > MAX_HTTP_STATUS_CODE:
                return CommandExecutionResult(
                    handled=True,
                    status_message=f"Status code must be in range {MIN_HTTP_STATUS_CODE}..{MAX_HTTP_STATUS_CODE}.",
                )
            headers = {"Content-Type": content_type}
            rule_name = self._runtime_config.add_static_response_rule(
                url=url,
                status_code=status_code,
                reason=_default_reason_phrase(status_code),
                headers=headers,
                body=body_text.encode("utf-8"),
                method=method,
                url_prefix=(action == "add-static-prefix"),
            )
            return CommandExecutionResult(handled=True, status_message=f"Added static policy: {rule_name}")

        if action in {"add-editor", "add-editor-prefix"}:
            method, value = _parse_modify_method_and_url(parts[2:])
            if not value:
                return CommandExecutionResult(
                    handled=True,
                    status_message="Usage: policy add-editor[ -prefix ] [METHOD] <url>",
                )
            try:
                normalized = self._runtime_config.add_open_editor_policy(
                    value,
                    method=method or DEFAULT_POLICY_METHOD,
                    url_prefix=(action == "add-editor-prefix"),
                )
            except ValueError as exc:
                return CommandExecutionResult(handled=True, status_message=str(exc))
            return CommandExecutionResult(handled=True, status_message=f"Added editor policy: {normalized}")

        if action == "remove-editor":
            method, value = _parse_modify_method_and_url(parts[2:])
            if not value:
                return CommandExecutionResult(
                    handled=True,
                    status_message="Usage: policy remove-editor [METHOD] <url>",
                )
            try:
                removed = self._runtime_config.remove_open_editor_policy(value, method=method)
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

        if action == "clear-editor":
            self._runtime_config.clear_open_editor_policies()
            return CommandExecutionResult(
                handled=True,
                status_message="Cleared all open-editor policies.",
            )

        if action == "remove":
            name = " ".join(parts[2:]).strip()
            if not name:
                return CommandExecutionResult(handled=True, status_message="Usage: policy remove <name>")
            try:
                removed = self._runtime_config.remove_policy_rule(name)
            except ValueError as exc:
                return CommandExecutionResult(handled=True, status_message=str(exc))
            if removed:
                return CommandExecutionResult(handled=True, status_message=f"Removed policy: {name}")
            return CommandExecutionResult(handled=True, status_message=f"Policy not found: {name}")

        if action in {"enable", "disable"}:
            name = " ".join(parts[2:]).strip()
            if not name:
                return CommandExecutionResult(
                    handled=True,
                    status_message=f"Usage: policy {action} <name>",
                )
            try:
                changed = self._runtime_config.set_policy_rule_enabled(name, enabled=(action == "enable"))
            except ValueError as exc:
                return CommandExecutionResult(handled=True, status_message=str(exc))
            if changed:
                state = "enabled" if action == "enable" else "disabled"
                return CommandExecutionResult(handled=True, status_message=f"Policy {state}: {name}")
            return CommandExecutionResult(handled=True, status_message=f"Policy not found: {name}")

        if action == "set-priority":
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
                changed = self._runtime_config.set_policy_rule_priority(name, priority=priority)
            except ValueError as exc:
                return CommandExecutionResult(handled=True, status_message=str(exc))
            if changed:
                return CommandExecutionResult(
                    handled=True,
                    status_message=f"Policy priority set: {name} -> {priority}",
                )
            return CommandExecutionResult(handled=True, status_message=f"Policy not found: {name}")

        if action == "edit":
            name = " ".join(parts[2:]).strip()
            if not name:
                return CommandExecutionResult(handled=True, status_message="Usage: policy edit <name>")
            try:
                rule = self._runtime_config.get_policy_rule(name)
            except ValueError as exc:
                return CommandExecutionResult(handled=True, status_message=str(exc))
            if rule is None:
                return CommandExecutionResult(handled=True, status_message=f"Policy not found: {name}")
            on_schedule_policy_edit(name)
            return CommandExecutionResult(handled=True, status_message=f"Opening policy editor: {name}")

        return CommandExecutionResult(
            handled=True,
            status_message=(
                "Usage: policy [show|add-editor|add-editor-prefix|remove-editor|clear-editor|"
                "add-static|add-static-prefix|set-priority|edit|remove|enable|disable] ..."
            ),
        )

    def _handle_mitm(self, parts: list[str]) -> CommandExecutionResult:
        if len(parts) == 1 or parts[1].lower() == "show":
            state = "on" if self._runtime_config.mitm_enabled else "off"
            certs_dir = self._runtime_config.mitm_certs_dir
            return CommandExecutionResult(
                handled=True,
                status_message=f"MITM: {state} certs_dir={certs_dir}",
            )

        action = parts[1].lower()
        if action == "on":
            self._runtime_config.set_mitm_enabled(True)
            return CommandExecutionResult(
                handled=True,
                status_message="MITM enabled in config (restart server to apply).",
            )
        if action == "off":
            self._runtime_config.set_mitm_enabled(False)
            return CommandExecutionResult(
                handled=True,
                status_message="MITM disabled in config (restart server to apply).",
            )
        if action == "certs-dir":
            path = " ".join(parts[2:]).strip()
            if not path:
                return CommandExecutionResult(
                    handled=True,
                    status_message="Usage: mitm certs-dir <path>",
                )
            target = self._runtime_config.set_mitm_certs_dir(path)
            return CommandExecutionResult(
                handled=True,
                status_message=f"MITM certs dir set to {target} (restart server to apply).",
            )

        return CommandExecutionResult(
            handled=True,
            status_message="Usage: mitm [show|on|off|certs-dir <path>]",
        )

    def _handle_config(
        self,
        parts: list[str],
        *,
        on_cache_toggle: Callable[[], None] | None,
    ) -> CommandExecutionResult:
        if len(parts) == 1 or parts[1].lower() == "show":
            path = self._runtime_config.config_path
            if path is None:
                return CommandExecutionResult(handled=True, status_message="Config path: <not attached>")
            return CommandExecutionResult(handled=True, status_message=f"Config path: {path}")

        action = parts[1].lower()
        if action == "save":
            target = " ".join(parts[2:]).strip()
            try:
                if target:
                    saved_path = self._runtime_config.save_to_path(target)
                else:
                    current = self._runtime_config.config_path
                    if current is None:
                        return CommandExecutionResult(
                            handled=True,
                            status_message="Usage: config save <path> (or attach --config at startup)",
                        )
                    self._runtime_config.save()
                    saved_path = current
            except (OSError, ValueError) as exc:
                return CommandExecutionResult(handled=True, status_message=f"Config save failed: {exc}")
            return CommandExecutionResult(handled=True, status_message=f"Config saved: {saved_path}")

        if action == "reload":
            before_cache = self._runtime_config.cache_invalidation_enabled
            try:
                reloaded = self._runtime_config.reload_from_attached_file()
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return CommandExecutionResult(handled=True, status_message=f"Config reload failed: {exc}")
            if not reloaded:
                return CommandExecutionResult(
                    handled=True,
                    status_message="No attached config path. Use: config save <path>",
                )
            if before_cache != self._runtime_config.cache_invalidation_enabled:
                _trigger_callback(on_cache_toggle)
            return CommandExecutionResult(
                handled=True,
                status_message=f"Config reloaded: {self._runtime_config.config_path}",
                updated_log_level=self._runtime_config.log_level,
            )

        return CommandExecutionResult(
            handled=True,
            status_message="Usage: config [show|save [path]|reload]",
        )


def _trigger_callback(callback: Callable[[], None] | None) -> None:
    if callback is None:
        return
    callback()


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
