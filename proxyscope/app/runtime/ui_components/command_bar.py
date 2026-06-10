from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, Static

from proxyscope.app.runtime.ui_components.rendering import plain_text
from proxyscope.app.runtime.ui_models import StatusBarModel


class CommandBar(Vertical):
    class Submitted(Message):
        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    def __init__(self) -> None:
        super().__init__(id="command-pane")

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Type a command and press Enter", id="command-input")
        yield Static(id="status-line")
        yield Static(id="config-line")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        command = event.value.strip()
        event.input.value = ""
        if command:
            self.post_message(self.Submitted(command))

    def render_model(self, model: StatusBarModel) -> None:
        self.query_one("#status-line", Static).update(plain_text(model.message))
        self.query_one("#config-line", Static).update(plain_text(model.config_text))

    def focus_input(self) -> None:
        self.query_one(Input).focus()
