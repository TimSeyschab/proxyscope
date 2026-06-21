import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "proxyscope"

ALLOWED_APP_IMPORTS: set[tuple[str, str]] = set()
MAX_CLASSES_PER_PACKAGE = 5


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

    def test_policy_domain_does_not_depend_on_app_proxy_or_mitm(self) -> None:
        violations: set[tuple[str, str]] = set()
        for path in (PACKAGE_ROOT / "policies").rglob("*.py"):
            source_module = _module_name(path)
            for imported_module in _absolute_imports(path):
                if imported_module.startswith(("proxyscope.app", "proxyscope.proxy", "proxyscope.mitm")):
                    violations.add((source_module, imported_module))

        self.assertEqual(violations, set(), f"Forbidden policy-domain imports: {sorted(violations)}")

    def test_config_domain_does_not_depend_on_app_proxy_or_mitm(self) -> None:
        violations: set[tuple[str, str]] = set()
        for path in (PACKAGE_ROOT / "config").rglob("*.py"):
            source_module = _module_name(path)
            for imported_module in _absolute_imports(path):
                if imported_module.startswith(("proxyscope.app", "proxyscope.proxy", "proxyscope.mitm")):
                    violations.add((source_module, imported_module))

        self.assertEqual(violations, set(), f"Forbidden config-domain imports: {sorted(violations)}")

    def test_processing_domain_does_not_depend_on_app_proxy_or_mitm(self) -> None:
        violations: set[tuple[str, str]] = set()
        for path in (PACKAGE_ROOT / "processing").rglob("*.py"):
            source_module = _module_name(path)
            for imported_module in _absolute_imports(path):
                if imported_module.startswith(("proxyscope.app", "proxyscope.proxy", "proxyscope.mitm")):
                    violations.add((source_module, imported_module))

        self.assertEqual(violations, set(), f"Forbidden processing-domain imports: {sorted(violations)}")

    def test_application_does_not_depend_on_outer_adapters(self) -> None:
        violations: set[tuple[str, str]] = set()
        for path in (PACKAGE_ROOT / "application").rglob("*.py"):
            source_module = _module_name(path)
            for imported_module in _absolute_imports(path):
                if imported_module.startswith(("textual", "proxyscope.app.", "proxyscope.adapters.")):
                    violations.add((source_module, imported_module))

        self.assertEqual(violations, set(), f"Forbidden application adapter imports: {sorted(violations)}")

    def test_command_handlers_do_not_depend_on_sibling_handlers(self) -> None:
        violations: set[tuple[str, str]] = set()
        handlers_dir = PACKAGE_ROOT / "application" / "commands" / "handlers"
        for path in handlers_dir.glob("*.py"):
            source_module = _module_name(path)
            for imported_module in _absolute_imports(path):
                if imported_module.startswith("proxyscope.application.commands.handlers."):
                    violations.add((source_module, imported_module))

        self.assertEqual(violations, set(), f"Forbidden command-handler sibling imports: {sorted(violations)}")

    def test_packages_define_at_most_five_direct_classes(self) -> None:
        violations: dict[str, list[str]] = {}
        package_dirs = {path.parent for path in PACKAGE_ROOT.rglob("*.py") if "__pycache__" not in path.parts}
        for package_dir in package_dirs:
            classes: list[str] = []
            for path in package_dir.glob("*.py"):
                classes.extend(f"{path.name}:{class_name}" for class_name in _top_level_classes(path))
            if len(classes) > MAX_CLASSES_PER_PACKAGE:
                violations[str(package_dir.relative_to(PROJECT_ROOT))] = sorted(classes)

        self.assertEqual(
            violations,
            {},
            f"Packages define more than {MAX_CLASSES_PER_PACKAGE} direct classes: {violations}",
        )


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imports


def _top_level_classes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _module_name(path: Path) -> str:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    return ".".join(relative.parts)


if __name__ == "__main__":
    unittest.main()
