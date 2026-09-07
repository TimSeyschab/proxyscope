import shlex
from typing import Callable

from proxyscope.application.commands.handlers.config import ConfigCommandHandler
from proxyscope.application.commands.handlers.settings import SettingsCommandHandler
from proxyscope.application.commands.runtime_result import CommandExecutionResult
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.runtime_settings import RuntimeSettingsState


class RuntimeCommandService:
    """
    Parse and execute runtime commands that mutate shared runtime configuration.
    """

    def __init__(
        self,
        *,
        settings: RuntimeSettingsState,
        configuration: RuntimeConfigurationService,
    ) -> None:
        self._settings_commands = SettingsCommandHandler(
            settings=settings,
            configuration=configuration,
        )
        self._config_commands = ConfigCommandHandler(
            settings=settings,
            configuration=configuration,
        )

    def execute(
        self,
        command: str,
        *,
        on_cache_toggle: Callable[[], None] | None,
    ) -> CommandExecutionResult:
        normalized = command.strip()
        if not normalized:
            return CommandExecutionResult(handled=False)

        try:
            parts = shlex.split(normalized)
        except ValueError as exc:
            return CommandExecutionResult(handled=True, status_message=f"Invalid command syntax: {exc}")
        return self.execute_parts(
            parts,
            on_cache_toggle=on_cache_toggle,
        )

    def execute_parts(
        self,
        parts: list[str],
        *,
        on_cache_toggle: Callable[[], None] | None,
    ) -> CommandExecutionResult:
        if not parts:
            return CommandExecutionResult(handled=False)
        cmd = parts[0].lower()
        handlers: dict[str, Callable[[], CommandExecutionResult]] = {
            "loglevel": lambda: self._settings_commands.execute(parts, on_cache_toggle=on_cache_toggle),
            "whitelist": lambda: self._settings_commands.execute(parts, on_cache_toggle=on_cache_toggle),
            "wl": lambda: self._settings_commands.execute(parts, on_cache_toggle=on_cache_toggle),
            "cache": lambda: self._settings_commands.execute(parts, on_cache_toggle=on_cache_toggle),
            "mitm": lambda: self._settings_commands.execute(parts, on_cache_toggle=on_cache_toggle),
            "config": lambda: self._config_commands.execute(parts, on_cache_toggle=on_cache_toggle),
        }
        handler = handlers.get(cmd)
        return CommandExecutionResult(handled=False) if handler is None else handler()
