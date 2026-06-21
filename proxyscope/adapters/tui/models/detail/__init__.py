from dataclasses import dataclass

from proxyscope.adapters.tui.models.types import DetailTab


@dataclass(frozen=True)
class RequestDetailModel:
    tab: DetailTab
    text: str
    has_response: bool
