from dataclasses import dataclass

from proxyscope.adapters.tui.models.admin import TabbedListModel
from proxyscope.adapters.tui.models.detail import RequestDetailModel
from proxyscope.adapters.tui.models.request import RequestListModel
from proxyscope.adapters.tui.models.status import StatusBarModel
from proxyscope.adapters.tui.models.types import ActivePane, DetailRatio, RuntimeView


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
