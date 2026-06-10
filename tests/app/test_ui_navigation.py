import unittest

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

    def test_selected_aux_items_clamp_cursor(self) -> None:
        state = RuntimeUIViewState(site_cursor=4, policy_cursor=4)
        navigation = RuntimeUINavigationService(state)

        site = navigation.selected_site(["example.com"])
        policy = navigation.selected_policy_name(["policy-a"])

        self.assertEqual(site, "example.com")
        self.assertEqual(policy, "policy-a")
        self.assertEqual(state.site_cursor, 0)
        self.assertEqual(state.policy_cursor, 0)

    def test_go_back_hides_sidebar_before_leaving_detail(self) -> None:
        state = RuntimeUIViewState(main_mode="request_detail", active_pane="detail")
        navigation = RuntimeUINavigationService(state)

        self.assertTrue(navigation.go_back())
        self.assertFalse(state.aux_visible)
        self.assertEqual(state.main_mode, "request_detail")

        self.assertTrue(navigation.go_back())
        self.assertEqual(state.main_mode, "requests")
        self.assertEqual(state.active_pane, "requests")

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
