import asyncio
import unittest

from textual.widgets import Input, OptionList

from proxyscope.adapters.tui.cli import RuntimeCLI
from proxyscope.adapters.tui.controller import RuntimeController
from proxyscope.adapters.tui.textual import RuntimeTextualApp
from proxyscope.adapters.tui.ui_controller import RuntimeUIController
from proxyscope.application.journal import RequestJournal
from tests.support.runtime_context import RuntimeTestContext, runtime_application_services


class TestRuntimeUIController(unittest.TestCase):
    def _controller(self, *, journal: RequestJournal | None = None) -> RuntimeCLI:
        config = RuntimeTestContext()
        return RuntimeCLI(
            application_services=runtime_application_services(
                config,
                request_journal=journal,
            ),
        )

    def test_runtime_cli_implements_ui_controller_protocol(self) -> None:
        controller = self._controller()

        self.assertIsInstance(controller, RuntimeUIController)

    def test_runtime_controller_implements_ui_controller_protocol(self) -> None:
        config = RuntimeTestContext()
        controller = RuntimeController(
            application_services=runtime_application_services(
                config,
                request_journal=RequestJournal(),
            ),
        )

        self.assertIsInstance(controller, RuntimeUIController)

    def test_public_navigation_actions_update_screen_model(self) -> None:
        journal = RequestJournal()
        journal.start_request(
            method="GET",
            path="/hello",
            start_line="GET /hello HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        controller = self._controller(journal=journal)

        controller.select_request(0)
        controller.open_selected_request_detail()
        controller.select_detail_tab("response")
        controller.select_aux_tab("policies")

        model = controller.build_screen_model()
        self.assertEqual(model.active_view, "admin")
        self.assertEqual(model.detail.tab, "response")
        self.assertEqual(model.active_pane, "policies")
        self.assertEqual(model.admin.active_key, "policies")

    def test_textual_shortcut_uses_public_controller_actions(self) -> None:
        async def run_test() -> None:
            controller = self._controller()
            app = RuntimeTextualApp(controller)

            async with app.run_test(size=(160, 42)) as pilot:
                await pilot.press("shift+p")
                await pilot.pause()

                model = controller.build_screen_model()
                self.assertEqual(model.active_view, "admin")
                self.assertEqual(model.active_pane, "policies")
                self.assertEqual(model.admin.active_key, "policies")

        asyncio.run(run_test())

    def test_textual_request_selection_opens_detail_view(self) -> None:
        async def run_test() -> None:
            journal = RequestJournal()
            journal.start_request(
                method="GET",
                path="/hello",
                start_line="GET /hello HTTP/1.1",
                headers={},
                body=b"",
                client_ip="127.0.0.1",
                target_host="example.com",
                target_port=80,
                protocol="http",
            )
            controller = self._controller(journal=journal)
            app = RuntimeTextualApp(controller)

            async with app.run_test(size=(160, 42)) as pilot:
                await pilot.press("shift+1")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()

                model = controller.build_screen_model()
                self.assertEqual(model.active_view, "traffic")
                self.assertTrue(model.detail_visible)
                self.assertEqual(model.active_pane, "detail")
                self.assertEqual(model.request_list.selected_request_id, 1)

        asyncio.run(run_test())

    def test_new_request_does_not_move_visual_focus_from_detail_view(self) -> None:
        async def run_test() -> None:
            journal = RequestJournal()
            journal.start_request(
                method="GET",
                path="/hello",
                start_line="GET /hello HTTP/1.1",
                headers={},
                body=b"",
                client_ip="127.0.0.1",
                target_host="example.com",
                target_port=80,
                protocol="http",
            )
            controller = self._controller(journal=journal)
            app = RuntimeTextualApp(controller)

            async with app.run_test(size=(160, 42)) as pilot:
                await pilot.press("shift+1")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()

                self.assertEqual(controller.build_screen_model().active_pane, "detail")
                focused_before = app.focused

                journal.start_request(
                    method="GET",
                    path="/new",
                    start_line="GET /new HTTP/1.1",
                    headers={},
                    body=b"",
                    client_ip="127.0.0.1",
                    target_host="example.com",
                    target_port=80,
                    protocol="http",
                )
                app._refresh_screen()
                await pilot.pause()

                model = controller.build_screen_model()
                self.assertEqual(model.active_view, "traffic")
                self.assertTrue(model.detail_visible)
                self.assertEqual(model.active_pane, "detail")
                self.assertEqual(model.request_list.selected_request_id, 1)
                self.assertIs(app.focused, focused_before)

        asyncio.run(run_test())

    def test_site_counter_refresh_does_not_leave_request_view(self) -> None:
        async def run_test() -> None:
            controller = self._controller()
            app = RuntimeTextualApp(controller)

            async with app.run_test(size=(160, 42)) as pilot:
                await pilot.press("shift+1")
                await pilot.pause()

                focused_before = app.focused
                controller.on_site_visit("example.com")
                app._refresh_screen()
                await pilot.pause()

                model = controller.build_screen_model()
                self.assertEqual(model.active_view, "traffic")
                self.assertEqual(model.active_pane, "requests")
                self.assertIs(app.focused, focused_before)

        asyncio.run(run_test())

    def test_textual_go_back_closes_open_detail_view(self) -> None:
        async def run_test() -> None:
            journal = RequestJournal()
            journal.start_request(
                method="GET",
                path="/hello",
                start_line="GET /hello HTTP/1.1",
                headers={},
                body=b"",
                client_ip="127.0.0.1",
                target_host="example.com",
                target_port=80,
                protocol="http",
            )
            controller = self._controller(journal=journal)
            app = RuntimeTextualApp(controller)

            async with app.run_test(size=(160, 42)) as pilot:
                await pilot.press("shift+1")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("shift+b")
                await pilot.pause()

                model = controller.build_screen_model()
                self.assertEqual(model.active_view, "traffic")
                self.assertFalse(model.detail_visible)
                self.assertEqual(model.active_pane, "requests")

        asyncio.run(run_test())

    def test_textual_tab_after_admin_switch_with_hidden_detail_focus_enters_admin_list(self) -> None:
        async def run_test() -> None:
            journal = RequestJournal()
            journal.start_request(
                method="GET",
                path="/hello",
                start_line="GET /hello HTTP/1.1",
                headers={},
                body=b"",
                client_ip="127.0.0.1",
                target_host="example.com",
                target_port=80,
                protocol="http",
            )
            controller = self._controller(journal=journal)
            app = RuntimeTextualApp(controller)

            async with app.run_test(size=(160, 42)) as pilot:
                await pilot.press("shift+1")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()

                controller.select_aux_tab("policies")
                app._refresh_screen()
                await pilot.pause()

                await pilot.press("tab")
                await pilot.pause()

                model = controller.build_screen_model()
                self.assertEqual(model.active_view, "admin")
                self.assertEqual(model.active_pane, "policies")

        asyncio.run(run_test())

    def test_textual_detail_ratio_shortcut_toggles_between_third_and_half(self) -> None:
        async def run_test() -> None:
            controller = self._controller()
            app = RuntimeTextualApp(controller)

            async with app.run_test(size=(160, 42)) as pilot:
                await pilot.press("shift+v")
                await pilot.pause()

                model = controller.build_screen_model()
                self.assertEqual(model.detail_ratio, "half")
                self.assertEqual(model.status_bar.message, "Detail width set to 1/2.")

                await pilot.press("shift+v")
                await pilot.pause()

                model = controller.build_screen_model()
                self.assertEqual(model.detail_ratio, "third")
                self.assertEqual(model.status_bar.message, "Detail width set to 1/3.")

        asyncio.run(run_test())

    def test_textual_colon_opens_command_modal_and_empty_submit_closes_it(self) -> None:
        async def run_test() -> None:
            controller = self._controller()
            app = RuntimeTextualApp(controller)

            async with app.run_test(size=(160, 42)) as pilot:
                await pilot.press(":")
                await pilot.pause()

                self.assertIsInstance(app.focused, Input)

                await pilot.press("enter")
                await pilot.pause()

                self.assertNotIsInstance(app.focused, Input)
                self.assertEqual(controller.build_screen_model().status_bar.message, "Press ':' for commands.")

        asyncio.run(run_test())

    def test_textual_policy_picker_shortcut_waits_for_selection(self) -> None:
        async def run_test() -> None:
            controller = self._controller()
            app = RuntimeTextualApp(controller)

            async with app.run_test(size=(160, 42)) as pilot:
                await pilot.press("shift+m")
                await pilot.pause()

                self.assertIsInstance(app.focused, OptionList)
                self.assertEqual(controller.build_screen_model().status_bar.message, "Press ':' for commands.")

                await pilot.press("enter")
                await pilot.pause()
                self.assertIsInstance(app.focused, OptionList)

                await pilot.press("enter")
                await pilot.pause()

                self.assertEqual(controller.build_screen_model().status_bar.message, "No request selected.")

        asyncio.run(run_test())

    def test_textual_command_modal_dispatches_submitted_command(self) -> None:
        async def run_test() -> None:
            controller = self._controller()
            app = RuntimeTextualApp(controller)

            async with app.run_test(size=(160, 42)) as pilot:
                await pilot.press(":")
                await pilot.pause()
                self.assertIsInstance(app.focused, Input)
                assert isinstance(app.focused, Input)
                app.focused.value = "not-a-command"

                await pilot.press("enter")
                await pilot.pause()

                self.assertEqual(controller.build_screen_model().status_bar.message, "Unknown command: not-a-command")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
