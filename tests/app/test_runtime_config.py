import logging
import tempfile
import unittest
from pathlib import Path

from proxyscope.app.config.runtime import RuntimeConfig, normalize_whitelist_entry
from proxyscope.policies.engine import PolicyEngine
from proxyscope.policies.models import StaticResponseAction
from proxyscope.policies.repository import InMemoryPolicyRepository


class TestRuntimeConfig(unittest.TestCase):
    def test_policy_mutations_use_injected_repository(self) -> None:
        repository = InMemoryPolicyRepository()
        config = RuntimeConfig(policy_repository=repository)

        config.add_open_editor_policy("https://example.com/edit")

        self.assertEqual(config.policy_rules(), repository.list())
        self.assertEqual(len(repository.list()), 1)

    def test_empty_whitelist_logs_everything(self) -> None:
        config = RuntimeConfig()
        self.assertTrue(config.should_log_for_host("example.com"))
        self.assertTrue(config.should_log_for_host(None))

    def test_non_empty_whitelist_filters_hosts(self) -> None:
        config = RuntimeConfig(log_whitelist=["example.com"])
        self.assertTrue(config.should_log_for_host("example.com"))
        self.assertFalse(config.should_log_for_host("google.com"))
        self.assertFalse(config.should_log_for_host(None))

    def test_set_log_level(self) -> None:
        config = RuntimeConfig()
        config.set_log_level("DEBUG")
        self.assertEqual(config.log_level, logging.DEBUG)

    def test_normalize_whitelist_entry_accepts_url(self) -> None:
        self.assertEqual(normalize_whitelist_entry("https://www.example.com/path"), "www.example.com")

    def test_cache_invalidation_toggle(self) -> None:
        config = RuntimeConfig()
        self.assertTrue(config.cache_invalidation_enabled)
        config.toggle_cache_invalidation()
        self.assertFalse(config.cache_invalidation_enabled)
        config.set_cache_invalidation_enabled(True)
        self.assertTrue(config.cache_invalidation_enabled)

    def test_mitm_settings_can_be_updated(self) -> None:
        config = RuntimeConfig()
        self.assertTrue(config.mitm_enabled)
        self.assertEqual(config.mitm_certs_dir, Path("certs"))

        config.set_mitm_enabled(False)
        config.set_mitm_certs_dir("custom-certs")

        self.assertFalse(config.mitm_enabled)
        self.assertEqual(config.mitm_certs_dir, Path("custom-certs"))

    def test_modification_whitelist(self) -> None:
        config = RuntimeConfig()
        added = config.add_modification_whitelist_entry("https://example.com/path?x=1")
        self.assertEqual(added, "GET https://example.com/path")
        self.assertTrue(
            PolicyEngine(config.policy_repository).should_modify_response_for_request(
                method="GET", url="https://example.com/path"
            )
        )
        self.assertFalse(
            PolicyEngine(config.policy_repository).should_modify_response_for_request(
                method="GET", url="https://example.com/other"
            )
        )

    def test_modification_whitelist_matches_http_https_variants(self) -> None:
        config = RuntimeConfig()
        config.add_modification_whitelist_entry("http://example.com/path")
        self.assertTrue(
            PolicyEngine(config.policy_repository).should_modify_response_for_request(
                method="GET", url="https://example.com/path"
            )
        )

    def test_modification_whitelist_host_wide_and_prefix(self) -> None:
        config = RuntimeConfig()
        config.add_modification_whitelist_entry("example.com")
        self.assertTrue(
            PolicyEngine(config.policy_repository).should_modify_response_for_request(
                method="GET", url="https://example.com/anything/here"
            )
        )

        config = RuntimeConfig()
        config.add_modification_whitelist_entry("https://example.com/api")
        self.assertTrue(
            PolicyEngine(config.policy_repository).should_modify_response_for_request(
                method="GET", url="https://example.com/api/v1/users"
            )
        )
        self.assertFalse(
            PolicyEngine(config.policy_repository).should_modify_response_for_request(
                method="GET", url="https://example.com/static/app.js"
            )
        )

    def test_modification_whitelist_is_method_sensitive(self) -> None:
        config = RuntimeConfig()
        config.add_modification_whitelist_entry("https://example.com/path", method="GET")
        self.assertTrue(
            PolicyEngine(config.policy_repository).should_modify_response_for_request(
                method="GET", url="https://example.com/path"
            )
        )
        self.assertFalse(
            PolicyEngine(config.policy_repository).should_modify_response_for_request(
                method="POST", url="https://example.com/path"
            )
        )

    def test_open_editor_policy_api_aliases_work(self) -> None:
        config = RuntimeConfig()
        config.add_open_editor_policy("https://example.com/path", method="POST")
        self.assertEqual(config.open_editor_policy_entries(), ("POST https://example.com/path",))
        removed = config.remove_open_editor_policy("https://example.com/path", method="POST")
        self.assertTrue(removed)
        self.assertEqual(config.open_editor_policy_entries(), ())

    def test_static_response_rule_matches_request(self) -> None:
        config = RuntimeConfig()
        config.add_static_response_rule(
            url="https://example.com/static",
            status_code=418,
            reason="I'm a teapot",
            headers={"Content-Type": "text/plain"},
            body=b"brew",
            method="GET",
        )
        template = PolicyEngine(config.policy_repository).get_static_response_template_for_request(
            method="GET",
            url="https://example.com/static",
        )
        self.assertIsNotNone(template)
        assert template is not None
        self.assertEqual(template.status_code, 418)
        self.assertEqual(template.reason, "I'm a teapot")
        self.assertEqual(template.headers.get("Content-Type"), "text/plain")
        self.assertEqual(template.body, b"brew")

    def test_runtime_config_persists_mutations_when_path_is_attached(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "runtime-config.json"
            config = RuntimeConfig.load_from_file(config_path)

            config.set_log_level("DEBUG")
            config.add_whitelist_entry("https://example.com")
            config.set_mitm_enabled(False)
            config.set_mitm_certs_dir("cert-bundle")
            config.add_modification_whitelist_entry("https://example.com/edit", method="POST")
            config.add_static_response_rule(
                url="https://example.com/mock",
                status_code=201,
                reason="Created",
                headers={"Content-Type": "application/json"},
                body=b'{"mock":true}',
                method="GET",
            )

            reloaded = RuntimeConfig.load_from_file(config_path)
            self.assertEqual(reloaded.log_level_name(), "DEBUG")
            self.assertEqual(reloaded.whitelist_entries(), ("example.com",))
            self.assertFalse(reloaded.mitm_enabled)
            self.assertEqual(reloaded.mitm_certs_dir, Path("cert-bundle"))
            self.assertTrue(
                PolicyEngine(reloaded.policy_repository).should_modify_response_for_request(
                    method="POST",
                    url="https://example.com/edit",
                )
            )
            template = PolicyEngine(reloaded.policy_repository).get_static_response_template_for_request(
                method="GET",
                url="https://example.com/mock",
            )
            self.assertIsNotNone(template)
            assert template is not None
            self.assertEqual(template.status_code, 201)
            self.assertEqual(template.reason, "Created")
            self.assertEqual(template.body, b'{"mock":true}')

    def test_policy_priority_prefers_higher_priority_rule(self) -> None:
        config = RuntimeConfig()
        config.add_static_response_rule(
            url="https://example.com/api",
            status_code=201,
            reason="Created",
            headers={"Content-Type": "text/plain"},
            body=b"prefix",
            method="GET",
            url_prefix=True,
            priority=1,
        )
        config.add_static_response_rule(
            url="https://example.com/api/users",
            status_code=418,
            reason="I'm a teapot",
            headers={"Content-Type": "text/plain"},
            body=b"exact",
            method="GET",
            priority=10,
        )

        template = PolicyEngine(config.policy_repository).get_static_response_template_for_request(
            method="GET",
            url="https://example.com/api/users",
        )
        self.assertIsNotNone(template)
        assert template is not None
        self.assertEqual(template.status_code, 418)
        self.assertEqual(template.body, b"exact")

    def test_open_editor_prefix_rule_can_be_added_explicitly(self) -> None:
        config = RuntimeConfig()
        config.add_open_editor_policy(
            "https://example.com/api",
            method="GET",
            url_prefix=True,
            priority=3,
        )

        self.assertTrue(
            PolicyEngine(config.policy_repository).should_modify_response_for_request(
                method="GET",
                url="https://example.com/api/v2/users",
            )
        )

        rule = config.policy_rules()[0]
        self.assertEqual(rule.priority, 3)
        self.assertEqual(rule.match.url_prefix, "https://example.com/api")
        self.assertIsNone(rule.match.url_exact)

    def test_reload_from_attached_file_hot_swaps_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "runtime-config.json"
            config = RuntimeConfig.load_from_file(config_path)
            config.set_log_level("INFO")
            config.set_cache_invalidation_enabled(True)
            config.set_mitm_enabled(True)
            config.set_mitm_certs_dir("before-certs")
            config.add_whitelist_entry("https://before.example")
            config.add_open_editor_policy("https://before.example/edit", method="GET")
            config.save()

            external = RuntimeConfig.load_from_file(config_path)
            external.set_log_level("DEBUG")
            external.set_cache_invalidation_enabled(False)
            external.set_mitm_enabled(False)
            external.set_mitm_certs_dir("after-certs")
            external.clear_whitelist()
            external.add_whitelist_entry("https://after.example")
            external.clear_open_editor_policies()
            external.add_open_editor_policy("https://after.example/edit", method="POST")
            external.save()

            reloaded = config.reload_from_attached_file()
            self.assertTrue(reloaded)
            self.assertEqual(config.log_level_name(), "DEBUG")
            self.assertFalse(config.cache_invalidation_enabled)
            self.assertFalse(config.mitm_enabled)
            self.assertEqual(config.mitm_certs_dir, Path("after-certs"))
            self.assertEqual(config.whitelist_entries(), ("after.example",))
            self.assertFalse(
                PolicyEngine(config.policy_repository).should_modify_response_for_request(
                    method="GET", url="https://before.example/edit"
                )
            )
            self.assertTrue(
                PolicyEngine(config.policy_repository).should_modify_response_for_request(
                    method="POST", url="https://after.example/edit"
                )
            )

    def test_policy_management_enable_disable_remove_and_descriptions(self) -> None:
        config = RuntimeConfig()
        config.add_modification_whitelist_entry("https://example.com/edit", method="GET")
        static_name = config.add_static_response_rule(
            url="https://example.com/mock",
            status_code=200,
            reason="OK",
            headers={"Content-Type": "text/plain"},
            body=b"mock",
            method="GET",
        )
        descriptions = config.policy_descriptions()
        self.assertEqual(len(descriptions), 2)
        self.assertTrue(any("open_editor" in item for item in descriptions))
        self.assertTrue(any("static_response" in item for item in descriptions))

        self.assertTrue(config.set_policy_rule_enabled(static_name, enabled=False))
        self.assertIsNone(
            PolicyEngine(config.policy_repository).get_static_response_template_for_request(
                method="GET", url="https://example.com/mock"
            )
        )
        self.assertTrue(config.set_policy_rule_enabled(static_name, enabled=True))
        self.assertIsNotNone(
            PolicyEngine(config.policy_repository).get_static_response_template_for_request(
                method="GET", url="https://example.com/mock"
            )
        )
        rule = config.get_policy_rule(static_name)
        self.assertIsNotNone(rule)
        assert rule is not None
        replaced = config.replace_policy_rule(
            static_name,
            type(rule)(
                name=rule.name,
                enabled=rule.enabled,
                priority=rule.priority,
                action=StaticResponseAction(
                    status_code=201,
                    reason="Created",
                    headers={"Content-Type": "application/json"},
                    body=b"{}",
                ),
                match=rule.match,
            ),
        )
        self.assertTrue(replaced)
        updated_template = PolicyEngine(config.policy_repository).get_static_response_template_for_request(
            method="GET", url="https://example.com/mock"
        )
        self.assertIsNotNone(updated_template)
        assert updated_template is not None
        self.assertEqual(updated_template.status_code, 201)
        self.assertTrue(config.remove_policy_rule(static_name))
        self.assertFalse(config.remove_policy_rule("missing-policy"))

    def test_policy_descriptions_follow_matching_precedence_order(self) -> None:
        config = RuntimeConfig()
        config.add_static_response_rule(
            url="https://example.com/base",
            method="GET",
            priority=0,
            name="low-priority",
        )
        config.add_static_response_rule(
            url="https://example.com/api",
            method="GET",
            priority=5,
            url_prefix=True,
            name="mid-priority-prefix",
        )
        config.add_static_response_rule(
            url="https://example.com/api/v1/users",
            method="GET",
            priority=5,
            name="high-priority-exact",
        )

        descriptions = config.policy_descriptions()
        ordered_names = [item.split(" ", 1)[0] for item in descriptions]
        self.assertEqual(
            ordered_names,
            ["high-priority-exact", "mid-priority-prefix", "low-priority"],
        )
