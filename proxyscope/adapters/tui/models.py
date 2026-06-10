from dataclasses import dataclass
from typing import Literal

MainMode = Literal["requests", "request_detail"]
ActivePane = Literal["requests", "detail", "aux"]
DetailTab = Literal["request", "response"]


@dataclass(frozen=True)
class RequestRowModel:
    request_id: int
    cells: tuple[str, str, str, str, str, str]


@dataclass(frozen=True)
class RequestListModel:
    title: str
    rows: list[RequestRowModel]
    cursor: int
    selected_request_id: int | None


@dataclass(frozen=True)
class RequestDetailModel:
    tab: DetailTab
    text: str
    has_response: bool


@dataclass(frozen=True)
class AuxPanelTabModel:
    key: str
    title: str
    items: list[str]
    cursor: int
    empty_label: str = "<empty>"


@dataclass(frozen=True)
class AuxPanelModel:
    visible: bool
    aux_tabs: list[AuxPanelTabModel]
    active_key: str


@dataclass(frozen=True)
class StatusBarModel:
    message: str
    config_text: str


@dataclass(frozen=True)
class RuntimeScreenModel:
    request_list: RequestListModel
    detail: RequestDetailModel
    aux: AuxPanelModel
    status_bar: StatusBarModel
    main_mode: MainMode
    active_pane: ActivePane
