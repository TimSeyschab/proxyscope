from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Static

from proxyscope.adapters.tui.components.contracts import REQUESTS_FOCUS, ComponentFocus
from proxyscope.adapters.tui.components.rendering import plain_text
from proxyscope.adapters.tui.models import RequestListModel

RequestListRowCells = tuple[str, str, str, str, str, str]


class RequestList(Vertical):
    focus_target: ComponentFocus = REQUESTS_FOCUS

    class Focused(Message):
        pass

    @classmethod
    def owns_focus(cls, focus: ComponentFocus) -> bool:
        return focus == cls.focus_target

    class Highlighted(Message):
        def __init__(self, cursor: int) -> None:
            super().__init__()
            self.cursor = cursor

    class Selected(Message):
        def __init__(self, cursor: int) -> None:
            super().__init__()
            self.cursor = cursor

    def __init__(self) -> None:
        super().__init__(id="main-pane", classes="pane")
        self._rows: tuple[RequestListRowCells, ...] = ()
        self._request_ids: tuple[int, ...] = ()
        self._row_offset = 0

    def compose(self) -> ComposeResult:
        yield Static(id="main-title", classes="pane-title")
        yield DataTable(id="requests")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("ID", "Status", "Method", "Host", "Path", "Duration")

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self.post_message(self.Focused())

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        self.post_message(self.Highlighted(self._row_offset + event.cursor_row))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.post_message(self.Selected(self._row_offset + event.cursor_row))

    def render_model(self, model: RequestListModel, *, active: bool) -> None:
        self.set_class(active, "-active")
        title = self.query_one("#main-title", Static)
        title.update(plain_text(model.title))
        title.set_class(active, "-active")

        table = self.query_one(DataTable)
        previous_scroll_y = table.scroll_y
        previous_selected_index = _index_of(self._request_ids, model.selected_request_id)
        rows = tuple(row.cells for row in model.rows)
        request_ids = tuple(row.request_id for row in model.rows)
        rows_changed = rows != self._rows or request_ids != self._request_ids or model.row_offset != self._row_offset
        if rows_changed:
            table.clear(columns=False)
            for row in rows:
                table.add_row(*row)
            self._rows = rows
            self._request_ids = request_ids
            self._row_offset = model.row_offset

        if model.rows:
            cursor = min(max(model.cursor - model.row_offset, 0), len(model.rows) - 1)
            if model.follow_top:
                table.move_cursor(row=cursor, animate=False, scroll=False)
                table.scroll_to(y=0, animate=False, immediate=True, force=True)
                return
            if rows_changed and previous_selected_index is None:
                table.move_cursor(row=cursor, animate=False, scroll=True)
                return
            table.move_cursor(row=cursor, animate=False, scroll=False)
            if rows_changed:
                scroll_y = _stable_scroll_y(
                    previous_scroll_y=previous_scroll_y,
                    previous_selected_index=previous_selected_index,
                    selected_index=cursor,
                )
                table.scroll_to(y=scroll_y, animate=False, immediate=True, force=True)

    def focus_list(self) -> None:
        self.query_one(DataTable).focus()


def _stable_scroll_y(
    *,
    previous_scroll_y: float,
    previous_selected_index: int | None,
    selected_index: int,
) -> float:
    if previous_selected_index is None or previous_selected_index == 0:
        return 0
    return max(0, previous_scroll_y + selected_index - previous_selected_index)


def _index_of(request_ids: tuple[int, ...], request_id: int | None) -> int | None:
    if request_id is None:
        return None
    try:
        return request_ids.index(request_id)
    except ValueError:
        return None
