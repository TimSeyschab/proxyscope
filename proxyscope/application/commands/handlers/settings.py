from typing import Callable

from proxyscope.application.commands.runtime_result import CommandExecutionResult
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.runtime_settings import RuntimeSettingsState


class SettingsCommandHandler:
    def __init__(
        self,
        *,
        settings: RuntimeSettingsState,
        configuration: RuntimeConfigurationService,
    ) -> None:
        self._settings = settings
        self._configuration = configuration

    def execute(
        self,
        parts: list[str],
        *,
        on_cache_toggle: Callable[[], None] | None,
    ) -> CommandExecutionResult:
        command = parts[0].lower()
        if command == "loglevel":
            return self._handle_loglevel(parts)
        if command in {"whitelist", "wl"}:
            return self._handle_whitelist(parts)
        if command == "cache":
            return self._handle_cache(parts, on_cache_toggle=on_cache_toggle)
        if command == "mitm":
            return self._handle_mitm(parts)
        return CommandExecutionResult(handled=False)

    def _handle_loglevel(self, parts: list[str]) -> CommandExecutionResult:
        if len(parts) == 1:
            return CommandExecutionResult(
                handled=True,
                status_message=f"Current log level: {self._settings.log_level_name()}",
            )
        try:
            new_level = self._settings.set_log_level(parts[1])
            self._configuration.save()
        except ValueError as exc:
            return CommandExecutionResult(handled=True, status_message=str(exc))
        return CommandExecutionResult(
            handled=True,
            status_message=f"Log level set to {self._settings.log_level_name()}",
            updated_log_level=new_level,
        )

    def _handle_whitelist(self, parts: list[str]) -> CommandExecutionResult:
        if len(parts) == 1 or parts[1].lower() == "show":
            entries = self._settings.whitelist_entries()
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
                added = self._settings.add_whitelist_entry(value)
                self._configuration.save()
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
                removed = self._settings.remove_whitelist_entry(value)
                if removed:
                    self._configuration.save()
            except ValueError as exc:
                return CommandExecutionResult(handled=True, status_message=str(exc))
            if removed:
                return CommandExecutionResult(
                    handled=True,
                    status_message=f"Removed from whitelist: {value}",
                )
            return CommandExecutionResult(handled=True, status_message=f"Not in whitelist: {value}")

        if action == "clear":
            self._settings.clear_whitelist()
            self._configuration.save()
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
            enabled = self._settings.cache_invalidation_enabled
            state = "on" if enabled else "off"
            return CommandExecutionResult(handled=True, status_message=f"Cache invalidation: {state}")

        action = parts[1].lower()
        if action == "on":
            self._settings.set_cache_invalidation_enabled(True)
            self._configuration.save()
            _trigger_callback(on_cache_toggle)
            return CommandExecutionResult(handled=True, status_message="Cache invalidation enabled.")
        if action == "off":
            self._settings.set_cache_invalidation_enabled(False)
            self._configuration.save()
            _trigger_callback(on_cache_toggle)
            return CommandExecutionResult(handled=True, status_message="Cache invalidation disabled.")
        if action == "toggle":
            enabled = self._settings.toggle_cache_invalidation()
            self._configuration.save()
            _trigger_callback(on_cache_toggle)
            state = "enabled" if enabled else "disabled"
            return CommandExecutionResult(handled=True, status_message=f"Cache invalidation {state}.")

        return CommandExecutionResult(
            handled=True,
            status_message="Usage: cache [show|on|off|toggle]",
        )

    def _handle_mitm(self, parts: list[str]) -> CommandExecutionResult:
        if len(parts) == 1 or parts[1].lower() == "show":
            state = "on" if self._settings.mitm_enabled else "off"
            certs_dir = self._settings.mitm_certs_dir
            return CommandExecutionResult(
                handled=True,
                status_message=f"MITM: {state} certs_dir={certs_dir}",
            )

        action = parts[1].lower()
        if action == "on":
            self._settings.set_mitm_enabled(True)
            self._configuration.save()
            return CommandExecutionResult(
                handled=True,
                status_message="MITM enabled in config (restart server to apply).",
            )
        if action == "spa":
            self._settings.set_mitm_enabled(True)
            self._settings.set_cache_invalidation_enabled(True)
            self._configuration.save()
            return CommandExecutionResult(
                handled=True,
                status_message="MITM SPA profile enabled: MITM on, cache invalidation on (restart server to apply).",
            )
        if action == "off":
            self._settings.set_mitm_enabled(False)
            self._configuration.save()
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
            target = self._settings.set_mitm_certs_dir(path)
            self._configuration.save()
            return CommandExecutionResult(
                handled=True,
                status_message=f"MITM certs dir set to {target} (restart server to apply).",
            )

        return CommandExecutionResult(
            handled=True,
            status_message="Usage: mitm [show|on|off|spa|certs-dir <path>]",
        )


def _trigger_callback(callback: Callable[[], None] | None) -> None:
    if callback is None:
        return
    callback()
