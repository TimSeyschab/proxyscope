import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "proxyscope"

ALLOWED_APP_IMPORTS: set[tuple[str, str]] = set()


class TestImportBoundaries(unittest.TestCase):
    def test_proxy_and_mitm_do_not_add_new_app_dependencies(self) -> None:
        violations: set[tuple[str, str]] = set()
        for package_name in ("proxy", "mitm"):
            package_dir = PACKAGE_ROOT / package_name
            for path in package_dir.rglob("*.py"):
                source_module = _module_name(path)
                for imported_module in _absolute_imports(path):
                    if imported_module.startswith("proxyscope.app"):
                        violations.add((source_module, imported_module))

        unexpected = violations - ALLOWED_APP_IMPORTS
        self.assertEqual(unexpected, set(), f"New forbidden app imports: {sorted(unexpected)}")


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imports


def _module_name(path: Path) -> str:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    return ".".join(relative.parts)


if __name__ == "__main__":
    unittest.main()
