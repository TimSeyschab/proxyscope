import unittest

from proxyscope.app.runtime.input import RuntimeInputController


class _FakeHost:
    def __init__(self) -> None:
        self._command_buffer = ""
        self._active_pane = "requests"
        self._aux_tab_key = "sites"
        self._main_mode = "requests"

        self.switched_to_requests = 0
        self.focused_tabs: list[str] = []
        self.toggle_aux_calls = 0
        self.executed_commands: list[str] = []

    def _move_focus(self, direction: int) -> None:
        _ = direction

    def _move_vertical(self, delta: int) -> None:
        _ = delta

    def _page_vertical(self, direction: int) -> None:
        _ = direction

    def _switch_to_request_list_mode(self) -> None:
        self.switched_to_requests += 1

    def _focus_aux_tab(self, tab_key: str) -> None:
        self.focused_tabs.append(tab_key)
        self._active_pane = "aux"
        self._aux_tab_key = tab_key

    def _toggle_aux_visibility(self) -> None:
        self.toggle_aux_calls += 1

    def _add_selected_site_to_whitelist(self) -> None:
        pass

    def _remove_selected_site_from_whitelist(self) -> None:
        pass

    def _enable_selected_policy(self) -> None:
        pass

    def _disable_selected_policy(self) -> None:
        pass

    def _remove_selected_policy(self) -> None:
        pass

    def _edit_selected_policy(self, stdscr: object) -> None:
        _ = stdscr

    def _add_selected_request_to_modify_whitelist(self) -> None:
        pass

    def _edit_and_resend_selected_request(self, stdscr: object) -> None:
        _ = stdscr

    def _toggle_detail_tab(self) -> None:
        pass

    def _open_selected_request_detail(self) -> None:
        self._main_mode = "request_detail"

    def execute_command(self, command: str) -> bool:
        self.executed_commands.append(command)
        return False


class TestRuntimeInputController(unittest.TestCase):
    def test_shift_b_switches_to_request_list_mode(self) -> None:
        host = _FakeHost()
        controller = RuntimeInputController()
        controller.handle_key(host, object(), ord("B"))
        self.assertEqual(host.switched_to_requests, 1)

    def test_shift_p_focuses_policies_tab(self) -> None:
        host = _FakeHost()
        controller = RuntimeInputController()
        controller.handle_key(host, object(), ord("P"))
        self.assertEqual(host.focused_tabs, ["policies"])

    def test_enter_executes_command_buffer(self) -> None:
        host = _FakeHost()
        host._command_buffer = "help"
        controller = RuntimeInputController()
        controller.handle_key(host, object(), 10)
        self.assertEqual(host.executed_commands, ["help"])
        self.assertEqual(host._command_buffer, "")

    def test_printable_input_appends_to_command_buffer(self) -> None:
        host = _FakeHost()
        controller = RuntimeInputController()
        controller.handle_key(host, object(), ord("a"))
        controller.handle_key(host, object(), ord("b"))
        self.assertEqual(host._command_buffer, "ab")


if __name__ == "__main__":
    unittest.main()
