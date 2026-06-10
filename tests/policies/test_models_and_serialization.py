import unittest

from proxyscope.policies.models import OpenEditorAction, PolicyRule, RequestMatchRule, StaticResponseAction
from proxyscope.policies.serialization import parse_policy_rule, serialize_policy_rule


class TestPolicyModels(unittest.TestCase):
    def test_open_editor_action_requires_no_invalid_companion_state(self) -> None:
        rule = PolicyRule(
            name="edit",
            enabled=True,
            priority=0,
            action=OpenEditorAction(),
            match=RequestMatchRule(methods=("GET",), url_exact="https://example.com/edit"),
        )

        self.assertIsInstance(rule.action, OpenEditorAction)

    def test_static_response_action_owns_complete_response(self) -> None:
        action = StaticResponseAction(status_code=201, reason="Created", headers={"X-Test": "yes"}, body=b"created")
        rule = PolicyRule(
            name="static",
            enabled=True,
            priority=0,
            action=action,
            match=RequestMatchRule(url_prefix="https://example.com/api"),
        )

        self.assertIs(rule.action, action)
        self.assertEqual(action.body, b"created")

    def test_invalid_policy_states_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PolicyRule(name=" ", enabled=True, priority=0, action=OpenEditorAction(), match=RequestMatchRule())
        with self.assertRaises(ValueError):
            RequestMatchRule(url_exact="https://example.com/a", url_prefix="https://example.com/")
        with self.assertRaises(ValueError):
            StaticResponseAction(status_code=700)


class TestPolicySerialization(unittest.TestCase):
    def test_roundtrip_preserves_typed_actions(self) -> None:
        rules = (
            PolicyRule(
                name="edit",
                enabled=True,
                priority=2,
                action=OpenEditorAction(),
                match=RequestMatchRule(methods=("POST",), url_exact="https://example.com/edit"),
            ),
            PolicyRule(
                name="static",
                enabled=True,
                priority=3,
                action=StaticResponseAction(status_code=202, reason="Accepted", body=b"\x00binary"),
                match=RequestMatchRule(url_prefix="https://example.com/api"),
            ),
        )

        parsed = tuple(parse_policy_rule(serialize_policy_rule(rule)) for rule in rules)

        self.assertEqual(parsed, rules)
        assert parsed[0] is not None
        assert parsed[1] is not None
        self.assertIsInstance(parsed[0].action, OpenEditorAction)
        self.assertIsInstance(parsed[1].action, StaticResponseAction)


if __name__ == "__main__":
    unittest.main()
