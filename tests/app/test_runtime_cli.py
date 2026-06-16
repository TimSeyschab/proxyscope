import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proxyscope.adapters.editing.response_editor import _decode_content_encoded_body
from proxyscope.adapters.tui.cli import RuntimeCLI
from proxyscope.application.journal import RequestJournal
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.policies.engine import PolicyEngine
from tests.support.runtime_context import RuntimeTestContext, runtime_dependencies


class TestRuntimeCLI(unittest.TestCase):
    def _journal_with_requests(self) -> RequestJournal:
        journal = RequestJournal()
        first = journal.start_request(
            method="GET",
            path="/alpha",
            start_line="GET /alpha HTTP/1.1",
            headers={"X-Test": "alpha"},
            body=b"hello world",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        journal.complete_request(
            first,
            status_code=200,
            reason="OK",
            start_line="HTTP/1.1 200 OK",
            headers={"Content-Type": "text/plain"},
            body=b"alpha response",
            duration_ms=10.0,
        )

        second = journal.start_request(
            method="POST",
            path="/beta",
            start_line="POST /beta HTTP/1.1",
            headers={"X-Test": "beta"},
            body=b"search me",
            client_ip="127.0.0.1",
            target_host="api.example.com",
            target_port=443,
            protocol="https-mitm",
        )
        journal.complete_request(
            second,
            status_code=404,
            reason="Not Found",
            start_line="HTTP/1.1 404 Not Found",
            headers={"Content-Type": "text/plain"},
            body=b"missing",
            duration_ms=11.0,
        )
        return journal

    def test_execute_help_command(self) -> None:
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        should_exit = cli.execute_command("help")
        self.assertFalse(should_exit)
        self.assertIn("filter", cli._status_message)  # type: ignore[attr-defined]
        self.assertIn("mitm", cli._status_message)  # type: ignore[attr-defined]

    def test_execute_question_mark_command_uses_help(self) -> None:
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )

        should_exit = cli.execute_command("?")

        self.assertFalse(should_exit)
        self.assertEqual(cli._status_message, cli.HELP_SUMMARY)  # type: ignore[attr-defined]

    def test_default_view_is_admin_sites(self) -> None:
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )

        model = cli.build_screen_model()
        self.assertEqual(model.active_view, "admin")
        self.assertEqual(model.admin.active_key, "sites")
        self.assertEqual(model.active_pane, "sites")

    def test_go_back_moves_detail_focus_to_request_list(self) -> None:
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
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=journal,
            response_modifier=ResponseModifierService(),
        )
        cli.open_selected_request_detail()

        cli.go_back()

        model = cli.build_screen_model()
        self.assertEqual(model.active_view, "traffic")
        self.assertFalse(model.detail_visible)
        self.assertEqual(model.active_pane, "requests")

    def test_toggle_detail_ratio_updates_screen_model(self) -> None:
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )

        cli.toggle_detail_ratio()

        model = cli.build_screen_model()
        self.assertEqual(model.detail_ratio, "half")
        self.assertEqual(model.status_bar.message, "Detail width set to 1/2.")

    def test_admin_tab_selection_is_remembered_when_switching_views(self) -> None:
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )

        cli.select_aux_tab("policies")
        cli.switch_view("traffic")
        cli.switch_view("admin")

        model = cli.build_screen_model()
        self.assertEqual(model.active_view, "admin")
        self.assertEqual(model.admin.active_key, "policies")
        self.assertEqual(model.active_pane, "policies")

    def test_selected_detail_request_stays_stable_when_new_entry_arrives(self) -> None:
        journal = RequestJournal()
        alpha_request_id = journal.start_request(
            method="GET",
            path="/alpha",
            start_line="GET /alpha HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        journal.start_request(
            method="GET",
            path="/beta",
            start_line="GET /beta HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=journal,
            response_modifier=ResponseModifierService(),
        )
        cli.select_request(1)
        cli.open_selected_request_detail()

        journal.start_request(
            method="GET",
            path="/gamma",
            start_line="GET /gamma HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        model = cli.build_screen_model()

        self.assertEqual(model.request_list.selected_request_id, alpha_request_id)
        self.assertEqual(model.request_list.cursor, 2)

    def test_request_follow_top_selects_newest_entry_when_new_entry_arrives(self) -> None:
        journal = RequestJournal()
        journal.start_request(
            method="GET",
            path="/alpha",
            start_line="GET /alpha HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        beta_request_id = journal.start_request(
            method="GET",
            path="/beta",
            start_line="GET /beta HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=journal,
            response_modifier=ResponseModifierService(),
        )
        cli.toggle_request_follow_top()

        model = cli.build_screen_model()
        self.assertEqual(model.request_list.selected_request_id, beta_request_id)
        self.assertEqual(model.request_list.cursor, 0)
        self.assertTrue(model.request_list.follow_top)

        gamma_request_id = journal.start_request(
            method="GET",
            path="/gamma",
            start_line="GET /gamma HTTP/1.1",
            headers={},
            body=b"",
            client_ip="127.0.0.1",
            target_host="example.com",
            target_port=80,
            protocol="http",
        )
        model = cli.build_screen_model()

        self.assertEqual(model.request_list.selected_request_id, gamma_request_id)
        self.assertEqual(model.request_list.cursor, 0)

    def test_execute_clear_command_clears_requests(self) -> None:
        journal = RequestJournal()
        request_id = journal.start_request(
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
        journal.complete_request(
            request_id,
            status_code=200,
            reason="OK",
            start_line="HTTP/1.1 200 OK",
            headers={},
            body=b"",
            duration_ms=12.3,
        )
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=journal,
            response_modifier=ResponseModifierService(),
        )
        should_exit = cli.execute_command("clear")
        self.assertFalse(should_exit)
        self.assertEqual(journal.list_entries(), ())

    def test_execute_quit_command_requests_shutdown(self) -> None:
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        called = {"shutdown": False}

        def shutdown() -> None:
            called["shutdown"] = True

        cli._shutdown_server = shutdown  # type: ignore[attr-defined]
        should_exit = cli.execute_command("quit")
        self.assertTrue(should_exit)
        self.assertTrue(called["shutdown"])

    def test_execute_loglevel_command_updates_config(self) -> None:
        config = RuntimeTestContext()
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        should_exit = cli.execute_command("loglevel DEBUG")
        self.assertFalse(should_exit)
        self.assertEqual(config.log_level_name(), "DEBUG")

    def test_execute_whitelist_commands(self) -> None:
        config = RuntimeTestContext()
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        cli.execute_command("whitelist add https://example.com/path")
        self.assertEqual(config.whitelist_entries(), ("example.com",))
        cli.execute_command("whitelist remove example.com")
        self.assertEqual(config.whitelist_entries(), ())

    def test_quick_add_selected_site_to_whitelist(self) -> None:
        config = RuntimeTestContext()
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        cli.on_site_visit("example.com")
        cli.add_selected_site_to_whitelist()
        self.assertEqual(config.whitelist_entries(), ("example.com",))

    def test_execute_cache_command_updates_config(self) -> None:
        config = RuntimeTestContext()
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        cli.execute_command("cache on")
        self.assertTrue(config.cache_invalidation_enabled)
        cli.execute_command("cache off")
        self.assertFalse(config.cache_invalidation_enabled)

    def test_cache_command_calls_toggle_hook(self) -> None:
        config = RuntimeTestContext()
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        called = {"count": 0}
        cli._on_cache_toggle = lambda: called.__setitem__("count", called["count"] + 1)  # type: ignore[attr-defined]
        cli.execute_command("cache on")
        self.assertEqual(called["count"], 1)

    def test_execute_mitm_commands_update_config(self) -> None:
        config = RuntimeTestContext()
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        cli.execute_command("mitm off")
        self.assertFalse(config.mitm_enabled)
        cli.execute_command("mitm certs-dir custom-certs")
        self.assertEqual(config.mitm_certs_dir, Path("custom-certs"))

    def test_execute_policy_add_editor_updates_config(self) -> None:
        config = RuntimeTestContext()
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        cli.execute_command("policy add-editor POST https://example.com/path")
        self.assertEqual(config.open_editor_policy_entries(), ("POST https://example.com/path",))

    def test_execute_policy_add_editor_with_explicit_method(self) -> None:
        config = RuntimeTestContext()
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        cli.execute_command("policy add-editor POST https://example.com/path")
        self.assertEqual(config.open_editor_policy_entries(), ("POST https://example.com/path",))

    def test_modify_command_is_no_longer_supported(self) -> None:
        config = RuntimeTestContext()
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        cli.execute_command("modify add https://example.com/path")
        self.assertEqual(config.open_editor_policy_entries(), ())

    def test_execute_policy_add_static_command_updates_config(self) -> None:
        config = RuntimeTestContext()
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        cli.execute_command("policy add-static GET https://example.com/mock 418 text/plain hello-policy")
        template = PolicyEngine(config.policy_repository).get_static_response_template_for_request(
            method="GET",
            url="https://example.com/mock",
        )
        self.assertIsNotNone(template)
        assert template is not None
        self.assertEqual(template.status_code, 418)
        self.assertEqual(template.body, b"hello-policy")

    def test_execute_policy_enable_disable_remove_commands(self) -> None:
        config = RuntimeTestContext()
        rule_name = config.add_static_response_rule(
            url="https://example.com/mock",
            status_code=200,
            reason="OK",
            headers={"Content-Type": "text/plain"},
            body=b"demo",
            method="GET",
        )
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        cli.execute_command(f"policy disable {rule_name}")
        template = PolicyEngine(config.policy_repository).get_static_response_template_for_request(
            method="GET",
            url="https://example.com/mock",
        )
        self.assertIsNone(template)

        cli.execute_command(f"policy enable {rule_name}")
        template = PolicyEngine(config.policy_repository).get_static_response_template_for_request(
            method="GET",
            url="https://example.com/mock",
        )
        self.assertIsNotNone(template)

        cli.execute_command(f"policy remove {rule_name}")
        self.assertEqual(len(config.policy_rules()), 0)

    def test_selected_policy_actions_require_policies_tab(self) -> None:
        config = RuntimeTestContext()
        rule_name = config.add_static_response_rule(
            url="https://example.com/mock",
            status_code=200,
            reason="OK",
            headers={"Content-Type": "text/plain"},
            body=b"demo",
            method="GET",
        )
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )

        cli.disable_selected_policy()

        self.assertEqual(cli._status_message, "Open Policies tab first (Shift+2, Shift+P).")  # type: ignore[attr-defined]
        self.assertIsNotNone(
            PolicyEngine(config.policy_repository).get_static_response_template_for_request(
                method="GET", url="https://example.com/mock"
            )
        )
        rule = config.get_policy_rule(rule_name)
        self.assertIsNotNone(rule)
        assert rule is not None
        self.assertTrue(rule.enabled)

    def test_selected_policy_actions_work_in_policies_tab(self) -> None:
        config = RuntimeTestContext()
        config.add_static_response_rule(
            url="https://example.com/mock",
            status_code=200,
            reason="OK",
            headers={"Content-Type": "text/plain"},
            body=b"demo",
            method="GET",
        )
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        cli.select_aux_tab("policies")

        cli.disable_selected_policy()

        self.assertIsNone(
            PolicyEngine(config.policy_repository).get_static_response_template_for_request(
                method="GET", url="https://example.com/mock"
            )
        )

    def test_policy_tab_order_matches_runtime_matching_precedence(self) -> None:
        config = RuntimeTestContext()
        config.add_static_response_rule(
            url="https://example.com/base",
            name="low-priority",
            priority=0,
            method="GET",
        )
        config.add_static_response_rule(
            url="https://example.com/api",
            name="mid-priority-prefix",
            priority=5,
            method="GET",
            url_prefix=True,
        )
        config.add_static_response_rule(
            url="https://example.com/api/v1/users",
            name="high-priority-exact",
            priority=5,
            method="GET",
        )
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )

        policies_tab = cli.build_screen_model().admin.tabs[1]
        self.assertIn("high-priority-exact", policies_tab.items[0])
        self.assertIn("mid-priority-prefix", policies_tab.items[1])
        self.assertIn("low-priority", policies_tab.items[2])

    def test_execute_policy_edit_command_schedules_editor(self) -> None:
        config = RuntimeTestContext()
        rule_name = config.add_static_response_rule(
            url="https://example.com/mock",
            status_code=200,
            reason="OK",
            headers={"Content-Type": "text/plain"},
            body=b"demo",
            method="GET",
        )
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )
        cli.execute_command(f"policy edit {rule_name}")
        self.assertEqual(cli._pending_policy_edit_name, rule_name)  # type: ignore[attr-defined]

    def test_shift_m_adds_editor_policy_and_opens_editor(self) -> None:
        config = RuntimeTestContext()
        with patch(
            "proxyscope.adapters.factory.edit_policy_rule_with_external_editor",
            return_value=(False, None, "cancelled"),
        ) as edit_mock:
            cli = RuntimeCLI(
                **runtime_dependencies(config),
                request_journal=self._journal_with_requests(),
                response_modifier=ResponseModifierService(),
            )
            cli.add_selected_request_to_editor_policy()

        self.assertTrue(config.open_editor_policy_entries())
        edit_mock.assert_called_once()
        self.assertEqual(cli._status_message, "cancelled")  # type: ignore[attr-defined]

    def test_decode_gzip_encoded_body(self) -> None:
        payload = b'{"ok":true}'
        encoded = gzip.compress(payload)
        decoded = _decode_content_encoded_body(encoded, "gzip")
        self.assertEqual(decoded, payload)

    def test_config_save_and_reload_commands(self) -> None:
        config = RuntimeTestContext()
        cli = RuntimeCLI(
            **runtime_dependencies(config),
            request_journal=RequestJournal(),
            response_modifier=ResponseModifierService(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "runtime-config.json"
            cli.execute_command(f"config save {path}")
            self.assertEqual(config.config_path, path)
            self.assertTrue(path.exists())

            external = RuntimeTestContext.load_from_file(path)
            external.set_log_level("DEBUG")
            external.add_open_editor_policy("https://example.com/hot", method="POST")
            external.save()

            cli.execute_command("config reload")
            self.assertEqual(config.log_level_name(), "DEBUG")
            self.assertTrue(
                PolicyEngine(config.policy_repository).should_modify_response_for_request(
                    method="POST",
                    url="https://example.com/hot",
                )
            )

    def test_execute_filter_commands_reduce_visible_entries(self) -> None:
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=self._journal_with_requests(),
            response_modifier=ResponseModifierService(),
        )

        cli.execute_command("filter host api.example.com")
        rows = cli.build_screen_model().request_list.rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].cells[3], "api.example.com")

        cli.execute_command("filter method POST")
        rows = cli.build_screen_model().request_list.rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].cells[2], "POST")

        cli.execute_command("filter status 404")
        rows = cli.build_screen_model().request_list.rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].cells[1], "404")

    def test_find_command_filters_by_text_and_clear_restores_entries(self) -> None:
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=self._journal_with_requests(),
            response_modifier=ResponseModifierService(),
        )

        cli.execute_command("find missing")
        rows = cli.build_screen_model().request_list.rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].cells[3], "api.example.com")

        cli.execute_command("find clear")
        self.assertEqual(len(cli.build_screen_model().request_list.rows), 2)

    def test_filter_clear_resets_all_request_filters(self) -> None:
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=self._journal_with_requests(),
            response_modifier=ResponseModifierService(),
        )

        cli.execute_command("filter host example.com")
        cli.execute_command("filter method GET")
        cli.execute_command("filter text alpha")
        self.assertEqual(len(cli.build_screen_model().request_list.rows), 1)

        cli.execute_command("filter clear")
        self.assertEqual(len(cli.build_screen_model().request_list.rows), 2)

    def test_export_command_writes_json_snapshot(self) -> None:
        cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=self._journal_with_requests(),
            response_modifier=ResponseModifierService(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "runtime-export.json"
            cli.execute_command(f"export json {path}")

            self.assertTrue(path.exists())
            self.assertIn("Exported json snapshot", cli._status_message)  # type: ignore[attr-defined]

    def test_session_save_and_load_commands(self) -> None:
        source_cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=self._journal_with_requests(),
            response_modifier=ResponseModifierService(),
        )
        target_journal = RequestJournal()
        target_cli = RuntimeCLI(
            **runtime_dependencies(RuntimeTestContext()),
            request_journal=target_journal,
            response_modifier=ResponseModifierService(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session.json"
            source_cli.execute_command(f"session save {path}")
            self.assertTrue(path.exists())

            target_cli.execute_command(f"session load {path}")
            self.assertEqual(len(target_journal.list_entries()), 2)
            self.assertIn("Loaded session snapshot", target_cli._status_message)  # type: ignore[attr-defined]
