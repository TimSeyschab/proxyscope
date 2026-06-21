from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget

from proxyscope.adapters.tui.components.command_bar import StatusFooter


class RuntimeScreenLayout(Vertical):
    def __init__(self, *content: Widget) -> None:
        super().__init__(id="root")
        self._content = content

    def compose(self) -> ComposeResult:
        with Vertical(id="view-content"):
            yield from self._content
        yield StatusFooter()
