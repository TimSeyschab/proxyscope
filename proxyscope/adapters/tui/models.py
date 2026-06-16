from dataclasses import dataclass
from typing import Literal

RuntimeView = Literal["traffic", "admin"]
ActivePane = Literal["requests", "detail", "sites", "policies"]
DetailTab = Literal["request", "response"]
DetailRatio = Literal["third", "half"]


@dataclass(frozen=True)
class RequestRowModel:
    request_id: int
    cells: tuple[str, str, str, str, str, str]


@dataclass(frozen=True)
class RequestListModel:
    title: str
    rows: list[RequestRowModel]
    cursor: int
    row_offset: int
    follow_top: bool
    selected_request_id: int | None


@dataclass(frozen=True)
class RequestDetailModel:
    tab: DetailTab
    text: str
    has_response: bool


@dataclass(frozen=True)
class TabbedListTabModel:
    key: str
    title: str
    items: list[str]
    cursor: int
    empty_label: str = "<empty>"


@dataclass(frozen=True)
class TabbedListModel:
    tabs: list[TabbedListTabModel]
    active_key: str


@dataclass(frozen=True)
class StatusBarModel:
    message: str
    config_text: str


@dataclass(frozen=True)
class RuntimeScreenModel:
    request_list: RequestListModel
    detail: RequestDetailModel
    detail_visible: bool
    detail_ratio: DetailRatio
    admin: TabbedListModel
    status_bar: StatusBarModel
    active_view: RuntimeView
    active_pane: ActivePane
