from dataclasses import dataclass
from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static

from proxyscope.adapters.tui.components.rendering import plain_text
from proxyscope.application.contracts import RequestPolicyAction, RequestPolicyTarget


@dataclass(frozen=True)
class RequestPolicySelection:
    target: RequestPolicyTarget
    action: RequestPolicyAction


class HelpModal(ModalScreen[None]):
    CSS = """
    HelpModal {
        align: center middle;
    }

    #help-dialog {
        width: 92;
        max-width: 90%;
        max-height: 85%;
        background: #11161a;
        border: round #d9a94f;
        padding: 1 2;
    }

    #help-title {
        color: #d9a94f;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #help-body {
        color: #e7e1d5;
        padding: 0;
    }

    #help-footer {
        color: #a8ada7;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("enter", "close", "Close", show=False),
    ]

    def __init__(self, help_text: str) -> None:
        super().__init__()
        self._help_text = help_text

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static(plain_text("HELP"), id="help-title")
            yield Static(plain_text(self._help_text), id="help-body")
            yield Static(plain_text("Esc or Enter closes this dialog."), id="help-footer")

    def action_close(self) -> None:
        self.dismiss()


class RequestPolicyPickerModal(ModalScreen[RequestPolicySelection | None]):
    CSS = """
    RequestPolicyPickerModal {
        align: center middle;
    }

    #request-policy-dialog {
        width: 56;
        max-width: 90%;
        background: #11161a;
        border: round #d9a94f;
        padding: 1 2;
    }

    #request-policy-title {
        color: #d9a94f;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #request-policy-disabled {
        color: #727971;
        padding: 0 0 1 0;
    }

    #request-policy-list {
        height: auto;
        background: transparent;
        color: #e7e1d5;
    }

    #request-policy-footer {
        color: #a8ada7;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [Binding("escape", "close", "Close", show=False)]

    def __init__(self, *, include_static_response: bool) -> None:
        super().__init__()
        self._include_static_response = include_static_response
        self._stage: Literal["target", "action"] = "target"
        self._actions: tuple[tuple[str, RequestPolicyAction], ...] = ()

    def compose(self) -> ComposeResult:
        with Vertical(id="request-policy-dialog"):
            yield Static(id="request-policy-title")
            yield Static(id="request-policy-disabled")
            yield OptionList(id="request-policy-list")
            yield Static(plain_text("Enter selects. Esc closes."), id="request-policy-footer")

    def on_mount(self) -> None:
        self._render_target_stage()
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if self._stage == "target":
            self._render_action_stage()
            return
        action = self._actions[event.option_index][1]
        self.dismiss(RequestPolicySelection(target="response", action=action))

    def action_close(self) -> None:
        self.dismiss(None)

    def _render_target_stage(self) -> None:
        self._stage = "target"
        self.query_one("#request-policy-title", Static).update(plain_text("POLICY TARGET"))
        self.query_one("#request-policy-disabled", Static).update(plain_text("Request (coming soon)"))
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        option_list.add_options(("Response",))
        option_list.highlighted = 0

    def _render_action_stage(self) -> None:
        self._stage = "action"
        self.query_one("#request-policy-title", Static).update(plain_text("RESPONSE POLICY"))
        self.query_one("#request-policy-disabled", Static).update("")
        actions: list[tuple[str, RequestPolicyAction]] = [
            ("Open editor policy", "open_editor_policy"),
        ]
        if self._include_static_response:
            actions.append(("Static response policy", "static_response_policy"))
        self._actions = tuple(actions)
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        option_list.add_options(tuple(label for label, _action in self._actions))
        option_list.highlighted = 0
