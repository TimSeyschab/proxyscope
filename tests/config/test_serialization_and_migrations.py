import json
import logging
import tempfile
import unittest
from pathlib import Path

from proxyscope.config.migrations import CURRENT_SCHEMA_VERSION
from proxyscope.config.serialization import ConfigValidationError, parse_config_payload, serialize_config_document
from proxyscope.config.settings import ConfigDocument, RuntimeSettings
from proxyscope.policies.engine import PolicyEngine
from proxyscope.policies.models import OpenEditorAction, PolicyRule, RequestMatchRule, StaticResponseAction
from proxyscope.policies.repository import InMemoryPolicyRepository
from tests.support.runtime_context import RuntimeTestContext


class TestConfigMigrations(unittest.TestCase):
    def test_legacy_config_is_migrated_without_user_input(self) -> None:
        document = parse_config_payload(
            {
                "log_level": "DEBUG",
                "log_whitelist": ["example.com"],
                "cache_invalidation_enabled": False,
                "mitm_enabled": True,
                "mitm_certs_dir": "legacy-certs",
                "policies": [
                    {
                        "name": "legacy-edit",
                        "enabled": True,
                        "priority": 0,
                        "action": {"type": "open_editor"},
                        "match": {"methods": ["GET"], "url_exact": "https://example.com/edit"},
                    }
                ],
            }
        )

        self.assertEqual(document.settings.log_level, logging.DEBUG)
        self.assertEqual(document.settings.mitm_certs_dir, Path("legacy-certs"))
        self.assertIsInstance(document.policies[0].action, OpenEditorAction)
        self.assertEqual(serialize_config_document(document)["schema_version"], CURRENT_SCHEMA_VERSION)

    def test_unsupported_schema_version_has_concrete_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported schema_version 99"):
            parse_config_payload({"schema_version": 99})

    def test_legacy_file_is_saved_as_current_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "config.json"
            path.write_text('{"log_level":"INFO","policies":[]}', encoding="utf-8")

            config = RuntimeTestContext.load_from_file(path)
            config.save()

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], CURRENT_SCHEMA_VERSION)
            self.assertIn("settings", saved)
            self.assertNotIn("log_level", saved)


class TestCurrentConfigSerialization(unittest.TestCase):
    def test_current_document_roundtrip(self) -> None:
        document = ConfigDocument(
            settings=RuntimeSettings.create(
                log_level=logging.WARNING,
                log_whitelist=("example.com",),
                cache_invalidation_enabled=False,
                mitm_enabled=False,
                mitm_certs_dir="custom-certs",
            ),
            policies=(
                PolicyRule(
                    "static",
                    True,
                    5,
                    StaticResponseAction(status_code=201, reason="Created", body=b"ok"),
                    RequestMatchRule(methods=("POST",), url_exact="https://example.com/create"),
                ),
            ),
        )

        parsed = parse_config_payload(serialize_config_document(document))

        self.assertEqual(parsed, document)

    def test_policy_shortcuts_support_demo_and_replay_configs(self) -> None:
        document = parse_config_payload(
            {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "settings": {},
                "policy_shortcuts": [
                    {
                        "name": "demo-health",
                        "match": "GET https://service.internal/health",
                        "respond": {"status": 200, "json": {"status": "ok"}},
                    },
                    {
                        "match": "POST https://service.internal/api/*",
                        "action": "open_editor",
                        "priority": 10,
                    },
                ],
            }
        )
        engine = PolicyEngine(InMemoryPolicyRepository(document.policies))

        response = engine.get_static_response_template_for_request(method="GET", url="https://service.internal/health")
        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response.headers["Content-Type"], "application/json")
        self.assertEqual(response.body, b'{"status":"ok"}')
        self.assertTrue(
            engine.should_modify_response_for_request(method="POST", url="https://service.internal/api/users")
        )

        canonical = serialize_config_document(document)
        self.assertNotIn("policy_shortcuts", canonical)
        self.assertEqual(len(canonical["policies"]), 2)

    def test_invalid_config_values_report_field_path(self) -> None:
        with self.assertRaisesRegex(ConfigValidationError, "settings.cache_invalidation_enabled must be a boolean"):
            parse_config_payload(
                {
                    "schema_version": CURRENT_SCHEMA_VERSION,
                    "settings": {"cache_invalidation_enabled": "yes"},
                }
            )
        with self.assertRaisesRegex(ConfigValidationError, r"policy_shortcuts\[0\].match"):
            parse_config_payload(
                {
                    "schema_version": CURRENT_SCHEMA_VERSION,
                    "settings": {},
                    "policy_shortcuts": [{"match": "invalid", "action": "open_editor"}],
                }
            )
        with self.assertRaisesRegex(ConfigValidationError, "settings contains unknown field"):
            parse_config_payload(
                {
                    "schema_version": CURRENT_SCHEMA_VERSION,
                    "settings": {"unknown": True},
                }
            )
        with self.assertRaisesRegex(ConfigValidationError, r"policies\[0\] contains unknown field"):
            parse_config_payload(
                {
                    "schema_version": CURRENT_SCHEMA_VERSION,
                    "settings": {},
                    "policies": [
                        {
                            "name": "invalid",
                            "enabled": True,
                            "priority": 0,
                            "action": {"type": "open_editor"},
                            "match": {},
                            "typo": True,
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
