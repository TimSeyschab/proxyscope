from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList, Static

from proxyscope.adapters.tui.components.rendering import format_tabs, plain_text
from proxyscope.adapters.tui.models import TabbedListModel


class TabbedListPane(Vertical):
    class Highlighted(Message):
        def __init__(self, cursor: int) -> None:
            super().__init__()
            self.cursor = cursor

    class Selected(Message):
        def __init__(self, cursor: int) -> None:
            super().__init__()
            self.cursor = cursor

    def __init__(self) -> None:
        super().__init__(id="admin-pane", classes="pane")
        self._items: tuple[str, ...] = ()
        self._active_key: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="admin-title", classes="pane-title")
        yield Static(id="admin-tabs")
        yield OptionList(id="admin-list")

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        self.post_message(self.Highlighted(event.option_index))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.post_message(self.Selected(event.option_index))

    def render_model(self, model: TabbedListModel, *, active: bool) -> None:
        self.set_class(active, "-active")
        active_tab = next((tab for tab in model.tabs if tab.key == model.active_key), None)
        title = self.query_one("#admin-title", Static)
        title.update(plain_text("ADMIN" if active_tab is None else active_tab.title.upper()))
        title.set_class(active, "-active")

        tabs = self.query_one("#admin-tabs", Static)
        tabs.display = len(model.tabs) > 1
        tabs.update(plain_text(format_tabs(tabs=model.tabs, active_key=model.active_key)))

        option_list = self.query_one(OptionList)
        items = tuple(
            active_tab.items
            if active_tab is not None and active_tab.items
            else (active_tab.empty_label if active_tab else "<empty>",)
        )
        if items != self._items or model.active_key != self._active_key:
            option_list.clear_options()
            option_list.add_options(items)
            self._items = items
            self._active_key = model.active_key
        if active_tab is None or not active_tab.items:
            option_list.highlighted = 0
            return
        option_list.highlighted = min(active_tab.cursor, len(active_tab.items) - 1)

    def focus_list(self) -> None:
        self.query_one(OptionList).focus()
