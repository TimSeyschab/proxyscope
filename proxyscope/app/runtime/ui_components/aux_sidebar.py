from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList, Static

from proxyscope.app.runtime.ui_components.rendering import format_sidebar_tabs, plain_text
from proxyscope.app.runtime.ui_models import AuxPanelModel


class AuxSidebar(Vertical):
    class Highlighted(Message):
        def __init__(self, cursor: int) -> None:
            super().__init__()
            self.cursor = cursor

    class Selected(Message):
        def __init__(self, cursor: int) -> None:
            super().__init__()
            self.cursor = cursor

    def __init__(self) -> None:
        super().__init__(id="sidebar-pane", classes="pane")
        self._items: tuple[str, ...] = ()
        self._active_key: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="sidebar-title", classes="pane-title")
        yield Static(id="sidebar-tabs")
        yield OptionList(id="sidebar-list")

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        self.post_message(self.Highlighted(event.option_index))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.post_message(self.Selected(event.option_index))

    def render_model(self, model: AuxPanelModel, *, active: bool) -> None:
        title = self.query_one("#sidebar-title", Static)
        title.update(plain_text("SIDEBAR"))
        title.set_class(active, "-active")
        self.query_one("#sidebar-tabs", Static).update(
            plain_text(format_sidebar_tabs(aux_tabs=model.aux_tabs, active_key=model.active_key))
        )

        option_list = self.query_one(OptionList)
        active_tab = next((tab for tab in model.aux_tabs if tab.key == model.active_key), None)
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

    def focus_sidebar(self) -> None:
        self.query_one(OptionList).focus()
