import asyncio
import unittest

from textual.widgets import Input

from proxyscope.adapters.tui.cli import RuntimeCLI
from proxyscope.adapters.tui.controller import RuntimeController
from proxyscope.adapters.tui.textual import RuntimeTextualApp
from proxyscope.adapters.tui.ui_controller import RuntimeUIController
from proxyscope.application.journal import RequestJournal
from proxyscope.application.response_edits import ResponseModifierService
from tests.support.runtime_context import RuntimeTestContext, runtime_dependencies


class TestRuntimeUIController(unittest.TestCase):
    def _controller(self, *, journal: RequestJournal | None = None) -> RuntimeCLI:
        return RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=journal or RequestJournal(),
            response_modifier=ResponseModifierService(),
        )

    def test_runtime_cli_implements_ui_controller_protocol(self) -> None:
        controller = self._controller()

        self.assertIsInstance(controller, RuntimeUIController)

    def test_runtime_controller_implements_ui_controller_protocol(self) -> None:
        controller = RuntimeController(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
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
                self.assertIsNotNone(app.focused)
                assert app.focused is not None
                self.assertEqual(app.focused.id, "admin-list")

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

                self.assertEqual(app.focused.id if app.focused is not None else None, "command-input")

                await pilot.press("enter")
                await pilot.pause()

                self.assertNotEqual(app.focused.id if app.focused is not None else None, "command-input")
                self.assertEqual(controller.build_screen_model().status_bar.message, "Press ':' for commands.")

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
