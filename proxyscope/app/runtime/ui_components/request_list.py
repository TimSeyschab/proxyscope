from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Static

from proxyscope.app.runtime.ui_components.rendering import plain_text
from proxyscope.app.runtime.ui_models import RequestListModel


class RequestList(Vertical):
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
        self._rows: tuple[tuple[str, str, str, str, str, str], ...] = ()

    def compose(self) -> ComposeResult:
        yield Static(id="main-title", classes="pane-title")
        yield DataTable(id="requests")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("ID", "Status", "Method", "Host", "Path", "Duration")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        self.post_message(self.Highlighted(event.cursor_row))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.post_message(self.Selected(event.cursor_row))

    def render_model(self, model: RequestListModel, *, active: bool) -> None:
        title = self.query_one("#main-title", Static)
        title.update(plain_text(model.title))
        title.set_class(active, "-active")

        table = self.query_one(DataTable)
        rows = tuple(row.cells for row in model.rows)
        if rows != self._rows:
            table.clear(columns=False)
            for row in rows:
                table.add_row(*row)
            self._rows = rows
        if model.rows:
            table.move_cursor(row=min(model.cursor, len(model.rows) - 1), animate=False, scroll=True)

    def focus_list(self) -> None:
        self.query_one(DataTable).focus()
