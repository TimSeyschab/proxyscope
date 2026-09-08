from collections.abc import Callable

from proxyscope.application.commands.runtime_result import CommandExecutionResult
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.runtime_settings import RuntimeSettingsState


class ConfigCommandHandler:
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
        if len(parts) == 1 or parts[1].lower() == "show":
            path = self._configuration.path
            return CommandExecutionResult(
                handled=True, status_message=f"Config path: {path if path is not None else '<not attached>'}"
            )

        action = parts[1].lower()
        if action == "save":
            return self._save_config(parts)
        if action == "reload":
            return self._reload_config(on_cache_toggle=on_cache_toggle)

        return CommandExecutionResult(
            handled=True,
            status_message="Usage: config [show|save [path]|reload]",
        )

    def _save_config(self, parts: list[str]) -> CommandExecutionResult:
        target = " ".join(parts[2:]).strip()
        if not target and self._configuration.path is None:
            return CommandExecutionResult(
                handled=True,
                status_message="Usage: config save <path> (or attach --config at startup)",
            )
        try:
            saved_path = self._configuration.save(target) if target else self._configuration.save()
        except (OSError, ValueError) as exc:
            return CommandExecutionResult(handled=True, status_message=f"Config save failed: {exc}")
        return CommandExecutionResult(handled=True, status_message=f"Config saved: {saved_path}")

    def _reload_config(self, *, on_cache_toggle: Callable[[], None] | None) -> CommandExecutionResult:
        before_cache = self._settings.cache_invalidation_enabled
        try:
            reloaded = self._configuration.reload()
        except (OSError, ValueError) as exc:
            return CommandExecutionResult(handled=True, status_message=f"Config reload failed: {exc}")
        if not reloaded:
            return CommandExecutionResult(
                handled=True,
                status_message="No attached config path. Use: config save <path>",
            )
        if before_cache != self._settings.cache_invalidation_enabled and on_cache_toggle is not None:
            on_cache_toggle()
        return CommandExecutionResult(
            handled=True,
            status_message=f"Config reloaded: {self._configuration.path}",
            updated_log_level=self._settings.log_level,
        )
