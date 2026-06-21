from dataclasses import dataclass


@dataclass(frozen=True)
class CommandExecutionResult:
    handled: bool
    status_message: str = ""
    updated_log_level: int | None = None
