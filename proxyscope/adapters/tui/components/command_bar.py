from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from proxyscope.adapters.tui.components.rendering import plain_text
from proxyscope.adapters.tui.models import StatusBarModel


class CommandModal(ModalScreen[str | None]):
    CSS = """
    CommandModal {
        align: center middle;
    }

    #command-dialog {
        width: 90;
        max-width: 90%;
        background: #11161a;
        border: round #d9a94f;
        padding: 1 2;
    }

    #command-input {
        border: none;
        background: #11161a;
        color: #e7e1d5;
        padding: 0;
    }
    """

    BINDINGS = [Binding("escape", "close", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="command-dialog"):
            yield Input(placeholder="Command", id="command-input")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        command = event.value.strip()
        self.dismiss(command or None)

    def action_close(self) -> None:
        self.dismiss(None)


class StatusFooter(Vertical):
    def __init__(self) -> None:
        super().__init__(id="status-pane")

    def compose(self) -> ComposeResult:
        yield Static(id="status-line")
        yield Static(id="config-line")

    def render_model(self, model: StatusBarModel) -> None:
        self.query_one("#status-line", Static).update(plain_text(model.message))
        self.query_one("#config-line", Static).update(plain_text(model.config_text))
