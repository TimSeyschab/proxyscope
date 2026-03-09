import curses
from typing import Literal, Protocol

ActivePane = Literal["requests", "detail", "aux"]
MainMode = Literal["requests", "request_detail"]


class RuntimeInputHost(Protocol):
    _command_buffer: str
    _active_pane: ActivePane
    _aux_tab_key: str
    _main_mode: MainMode

    def _move_focus(self, direction: int) -> None: ...

    def _move_vertical(self, delta: int) -> None: ...

    def _page_vertical(self, direction: int) -> None: ...

    def _switch_to_request_list_mode(self) -> None: ...

    def _focus_aux_tab(self, tab_key: str) -> None: ...

    def _toggle_aux_visibility(self) -> None: ...

    def _add_selected_site_to_whitelist(self) -> None: ...

    def _remove_selected_site_from_whitelist(self) -> None: ...

    def _enable_selected_policy(self) -> None: ...

    def _disable_selected_policy(self) -> None: ...

    def _remove_selected_policy(self) -> None: ...

    def _edit_selected_policy(self, stdscr: "curses._CursesWindow") -> None: ...

    def _add_selected_request_to_modify_whitelist(self) -> None: ...

    def _edit_and_resend_selected_request(self, stdscr: "curses._CursesWindow") -> None: ...

    def _toggle_detail_tab(self) -> None: ...

    def _open_selected_request_detail(self) -> None: ...

    def execute_command(self, command: str) -> bool: ...


class RuntimeInputController:
    def __init__(self) -> None:
        self._key_btab = getattr(curses, "KEY_BTAB", -1)

    def handle_key(self, host: RuntimeInputHost, stdscr: "curses._CursesWindow", key: int) -> None:
        if key == -1:
            return

        if key == curses.KEY_LEFT:
            host._move_focus(-1)
            return

        if key == curses.KEY_RIGHT:
            host._move_focus(1)
            return

        if key == curses.KEY_UP:
            host._move_vertical(-1)
            return

        if key == curses.KEY_DOWN:
            host._move_vertical(1)
            return

        if key == curses.KEY_PPAGE:
            host._page_vertical(-1)
            return

        if key == curses.KEY_NPAGE:
            host._page_vertical(1)
            return

        if key == ord("B") and not host._command_buffer:
            host._switch_to_request_list_mode()
            return

        if key == ord("P") and not host._command_buffer:
            host._focus_aux_tab("policies")
            return

        if key == ord("S") and not host._command_buffer:
            host._focus_aux_tab("sites")
            return

        if key == ord("V") and not host._command_buffer:
            host._toggle_aux_visibility()
            return

        if key == ord("A") and not host._command_buffer and host._active_pane == "aux" and host._aux_tab_key == "sites":
            host._add_selected_site_to_whitelist()
            return

        if key == ord("D") and not host._command_buffer and host._active_pane == "aux" and host._aux_tab_key == "sites":
            host._remove_selected_site_from_whitelist()
            return

        if key == ord("E") and not host._command_buffer and host._active_pane == "aux" and host._aux_tab_key == "policies":
            host._enable_selected_policy()
            return

        if key == ord("D") and not host._command_buffer and host._active_pane == "aux" and host._aux_tab_key == "policies":
            host._disable_selected_policy()
            return

        if key == ord("X") and not host._command_buffer and host._active_pane == "aux" and host._aux_tab_key == "policies":
            host._remove_selected_policy()
            return

        if key == ord("I") and not host._command_buffer and host._active_pane == "aux" and host._aux_tab_key == "policies":
            host._edit_selected_policy(stdscr)
            return

        if key == ord("M") and not host._command_buffer:
            host._add_selected_request_to_modify_whitelist()
            return

        if key == ord("R") and not host._command_buffer:
            host._edit_and_resend_selected_request(stdscr)
            return

        if key == ord("T") and not host._command_buffer and host._main_mode == "request_detail":
            host._toggle_detail_tab()
            return

        if key in (9, self._key_btab) and not host._command_buffer and host._main_mode == "request_detail":
            host._toggle_detail_tab()
            return

        if key in (10, 13):
            if host._command_buffer:
                command = host._command_buffer
                host._command_buffer = ""
                host.execute_command(command)
                return
            host._open_selected_request_detail()
            return

        if key in (curses.KEY_BACKSPACE, 127, 8):
            host._command_buffer = host._command_buffer[:-1]
            return

        if 32 <= key <= 126:
            host._command_buffer += chr(key)
