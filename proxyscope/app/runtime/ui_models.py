from dataclasses import dataclass
from typing import Literal

from proxyscope.app.runtime.journal import LoggedExchange

MainMode = Literal["requests", "request_detail"]
ActivePane = Literal["requests", "detail", "aux"]
DetailTab = Literal["request", "response"]


@dataclass(frozen=True)
class AuxPanelTabModel:
    key: str
    title: str
    items: list[str]
    cursor: int
    empty_label: str = "<empty>"


@dataclass(frozen=True)
class RuntimeScreenModel:
    request_title: str
    request_entries: list[LoggedExchange]
    request_cursor: int
    main_mode: MainMode
    active_pane: ActivePane
    detail_tab: DetailTab
    aux_visible: bool
    aux_tabs: list[AuxPanelTabModel]
    aux_active_key: str
    command_buffer: str
    status_message: str
    config_text: str
