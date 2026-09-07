import unittest

from proxyscope.adapters.tui.components.contracts import detail_focus
from proxyscope.adapters.tui.navigation import RuntimeUINavigationService
from proxyscope.adapters.tui.state import RuntimeUIViewState
from proxyscope.application.journal import LoggedExchange, RequestJournal


class TestRuntimeUINavigationService(unittest.TestCase):
    def test_selected_request_stays_stable_when_entry_is_inserted(self) -> None:
        state = RuntimeUIViewState()
        navigation = RuntimeUINavigationService(state)
        entries = self._entries("/beta", "/alpha")

        navigation.select_request(entries, 1)
        selected_id = state.selected_request_id

        updated_entries = self._entries("/gamma", "/beta", "/alpha")
        navigation.sync_request_selection(updated_entries)

        self.assertEqual(state.selected_request_id, selected_id)
        self.assertEqual(state.request_cursor, 2)

    def test_selected_request_clamps_cursor(self) -> None:
        state = RuntimeUIViewState()
        navigation = RuntimeUINavigationService(state)
        entries = self._entries("/beta", "/alpha")

        selected = navigation.selected_request(entries)
        navigation.select_request(entries, 20)

        self.assertIsNotNone(selected)
        self.assertEqual(state.request_cursor, 1)
        self.assertEqual(state.selected_request_id, entries[1].request_id)

    def test_selected_admin_items_clamp_cursor(self) -> None:
        state = RuntimeUIViewState(site_cursor=4, policy_cursor=4)
        navigation = RuntimeUINavigationService(state)

        site = navigation.selected_site(["example.com"])
        policy = navigation.selected_policy_name(["policy-a"])

        self.assertEqual(site, "example.com")
        self.assertEqual(policy, "policy-a")
        self.assertEqual(state.site_cursor, 0)
        self.assertEqual(state.policy_cursor, 0)

    def test_go_back_closes_visible_detail(self) -> None:
        state = RuntimeUIViewState(detail_visible=True)
        state.set_active_focus(detail_focus("request"))
        navigation = RuntimeUINavigationService(state)

        self.assertTrue(navigation.go_back())
        self.assertFalse(state.detail_visible)
        self.assertEqual(state.active_pane, "requests")

        self.assertFalse(navigation.go_back())
        self.assertEqual(state.active_view, "traffic")

    def test_toggle_detail_ratio_keeps_selection_state(self) -> None:
        state = RuntimeUIViewState(detail_ratio="third")
        navigation = RuntimeUINavigationService(state)

        navigation.toggle_detail_ratio()

        self.assertEqual(state.detail_ratio, "half")

    def test_admin_view_remembers_selected_tab(self) -> None:
        state = RuntimeUIViewState()
        navigation = RuntimeUINavigationService(state)

        navigation.select_aux_tab("policies")
        navigation.switch_view("traffic")
        navigation.switch_view("admin")

        self.assertEqual(state.active_view, "admin")
        self.assertEqual(state.admin_tab_key, "policies")
        self.assertEqual(state.active_pane, "policies")

    def _entries(self, *paths: str) -> list[LoggedExchange]:
        journal = RequestJournal()
        entries: list[LoggedExchange] = []
        for path in reversed(paths):
            request_id = journal.start_request(
                method="GET",
                path=path,
                start_line=f"GET {path} HTTP/1.1",
                headers={},
                body=b"",
                client_ip="127.0.0.1",
                target_host="example.com",
                target_port=80,
                protocol="http",
            )
            entry = journal.get_entry(request_id)
            assert entry is not None
            entries.insert(0, entry)
        return entries


if __name__ == "__main__":
    unittest.main()
