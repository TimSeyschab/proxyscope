from dataclasses import dataclass


@dataclass(frozen=True)
class StatusBarModel:
    message: str
    config_text: str
