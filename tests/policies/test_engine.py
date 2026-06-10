import unittest

from proxyscope.policies.engine import PolicyEngine
from proxyscope.policies.models import OpenEditorAction, PolicyRule, RequestMatchRule, StaticResponseAction
from proxyscope.policies.repository import InMemoryPolicyRepository


class TestPolicyEngine(unittest.TestCase):
    def test_evaluate_returns_typed_action(self) -> None:
        action = StaticResponseAction(status_code=204, reason="No Content")
        engine = PolicyEngine(
            InMemoryPolicyRepository(
                [PolicyRule("static", True, 0, action, RequestMatchRule(url_exact="https://example.com/a"))]
            )
        )

        evaluation = engine.evaluate(method="GET", url="https://example.com/a")

        self.assertEqual(evaluation.action, action)
        self.assertEqual(evaluation.rule.name if evaluation.rule else None, "static")

    def test_priority_exactness_and_static_tie_break_are_deterministic(self) -> None:
        repository = InMemoryPolicyRepository(
            [
                PolicyRule(
                    "prefix-high",
                    True,
                    5,
                    OpenEditorAction(),
                    RequestMatchRule(url_prefix="https://example.com/api"),
                ),
                PolicyRule(
                    "exact-high",
                    True,
                    5,
                    OpenEditorAction(),
                    RequestMatchRule(url_exact="https://example.com/api/users"),
                ),
                PolicyRule(
                    "static-high",
                    True,
                    5,
                    StaticResponseAction(body=b"static"),
                    RequestMatchRule(url_exact="https://example.com/api/users"),
                ),
            ]
        )
        engine = PolicyEngine(repository)

        evaluation = engine.evaluate(method="GET", url="https://example.com/api/users")

        self.assertEqual(evaluation.rule.name if evaluation.rule else None, "static-high")
        self.assertIsInstance(evaluation.action, StaticResponseAction)

    def test_matching_is_method_sensitive_and_supports_http_https_variants(self) -> None:
        engine = PolicyEngine(
            InMemoryPolicyRepository(
                [
                    PolicyRule(
                        "edit",
                        True,
                        0,
                        OpenEditorAction(),
                        RequestMatchRule(methods=("POST",), url_exact="http://example.com/edit"),
                    )
                ]
            )
        )

        self.assertIsInstance(engine.evaluate(method="POST", url="https://example.com/edit").action, OpenEditorAction)
        self.assertIsNone(engine.evaluate(method="GET", url="https://example.com/edit").action)

    def test_disabled_and_unmatched_rules_return_empty_evaluation(self) -> None:
        engine = PolicyEngine(
            InMemoryPolicyRepository(
                [
                    PolicyRule(
                        "disabled", False, 0, OpenEditorAction(), RequestMatchRule(url_exact="https://example.com")
                    )
                ]
            )
        )

        self.assertIsNone(engine.evaluate(method="GET", url="https://example.com").action)


if __name__ == "__main__":
    unittest.main()
