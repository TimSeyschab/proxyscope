import unittest

from proxyscope.policies.models import OpenEditorAction, PolicyRule, RequestMatchRule
from proxyscope.policies.repository import InMemoryPolicyRepository, PolicyRepository


def _rule(name: str, *, priority: int = 0) -> PolicyRule:
    return PolicyRule(name, True, priority, OpenEditorAction(), RequestMatchRule())


class TestInMemoryPolicyRepositoryContract(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryPolicyRepository()

    def test_implements_repository_port(self) -> None:
        self.assertIsInstance(self.repository, PolicyRepository)

    def test_add_get_replace_remove_and_replace_all(self) -> None:
        first = _rule("first")
        replacement = _rule("first", priority=10)
        self.repository.add(first)

        self.assertEqual(self.repository.list(), (first,))
        self.assertEqual(self.repository.get("first"), first)
        self.assertTrue(self.repository.replace("first", replacement))
        self.assertEqual(self.repository.get("first"), replacement)
        self.assertFalse(self.repository.replace("missing", replacement))
        self.assertTrue(self.repository.remove("first"))
        self.assertFalse(self.repository.remove("first"))

        final = (_rule("second"), _rule("third"))
        self.repository.replace_all(final)
        self.assertEqual(self.repository.list(), final)


if __name__ == "__main__":
    unittest.main()
