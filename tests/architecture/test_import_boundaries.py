import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "proxyscope"

ALLOWED_APP_IMPORTS: set[tuple[str, str]] = set()
MAX_CLASSES_PER_PACKAGE = 5
MAX_CLASSES_PER_PACKAGE_OVERRIDES = {
    # Event and traffic-rule packages intentionally expose cohesive type families.
    "proxyscope/application/configuration": 8,
    "proxyscope/contracts/events": 20,
    "proxyscope/contracts/traffic_rules": 12,
}


class TestImportBoundaries(unittest.TestCase):
    def test_proxy_and_mitm_do_not_add_new_app_dependencies(self) -> None:
        violations: set[tuple[str, str]] = set()
        for package_dir in (PACKAGE_ROOT / "adapters" / "proxy", PACKAGE_ROOT / "adapters" / "mitm"):
            for path in package_dir.rglob("*.py"):
                source_module = _module_name(path)
                for imported_module in _absolute_imports(path):
                    if imported_module == "proxyscope.bootstrap" or imported_module.startswith("proxyscope.bootstrap."):
                        violations.add((source_module, imported_module))

        unexpected = violations - ALLOWED_APP_IMPORTS
        self.assertEqual(unexpected, set(), f"New forbidden app imports: {sorted(unexpected)}")

    def test_proxy_does_not_construct_mitm_adapter(self) -> None:
        violations: set[tuple[str, str]] = set()
        for path in (PACKAGE_ROOT / "adapters" / "proxy").rglob("*.py"):
            source_module = _module_name(path)
            for imported_module in _absolute_imports(path):
                if imported_module.startswith("proxyscope.adapters.mitm"):
                    violations.add((source_module, imported_module))

        self.assertEqual(violations, set(), f"Proxy must not import MITM adapter code: {sorted(violations)}")

    def test_application_traffic_rule_and_processing_modules_do_not_depend_on_adapters(self) -> None:
        violations: set[tuple[str, str]] = set()
        for package_dir in (PACKAGE_ROOT / "application" / "traffic_rules", PACKAGE_ROOT / "application" / "processing"):
            for path in package_dir.rglob("*.py"):
                source_module = _module_name(path)
                for imported_module in _absolute_imports(path):
                    if imported_module == "proxyscope.bootstrap" or imported_module.startswith(
                        ("proxyscope.bootstrap.", "proxyscope.adapters.")
                    ):
                        violations.add((source_module, imported_module))
        self.assertEqual(violations, set(), f"Forbidden application-domain imports: {sorted(violations)}")

    def test_application_does_not_depend_on_outer_adapters(self) -> None:
        violations: set[tuple[str, str]] = set()
        for path in (PACKAGE_ROOT / "application").rglob("*.py"):
            source_module = _module_name(path)
            for imported_module in _absolute_imports(path):
                if imported_module.startswith(
                    ("textual", "proxyscope.bootstrap.", "proxyscope.adapters.", "proxyscope.components.")
                ):
                    violations.add((source_module, imported_module))

        self.assertEqual(violations, set(), f"Forbidden application adapter imports: {sorted(violations)}")

    def test_component_contracts_do_not_depend_on_outer_layers(self) -> None:
        forbidden_prefixes = ("textual", "proxyscope.adapters.", "proxyscope.bootstrap.", "proxyscope.proxy")
        violations: set[tuple[str, str]] = set()
        for path in (PACKAGE_ROOT / "application" / "components").rglob("*.py"):
            source_module = _module_name(path)
            for imported_module in _absolute_imports(path):
                if imported_module == "proxyscope.bootstrap" or imported_module.startswith(forbidden_prefixes):
                    violations.add((source_module, imported_module))

        self.assertEqual(violations, set(), f"Forbidden component-contract imports: {sorted(violations)}")

    def test_command_handlers_do_not_depend_on_sibling_handlers(self) -> None:
        violations: set[tuple[str, str]] = set()
        handlers_dir = PACKAGE_ROOT / "application" / "commands" / "handlers"
        for path in handlers_dir.glob("*.py"):
            source_module = _module_name(path)
            for imported_module in _absolute_imports(path):
                if imported_module.startswith("proxyscope.application.commands.handlers."):
                    violations.add((source_module, imported_module))

        self.assertEqual(violations, set(), f"Forbidden command-handler sibling imports: {sorted(violations)}")

    def test_components_use_ports_instead_of_application_implementations(self) -> None:
        forbidden_prefixes = (
            "proxyscope.application.services",
            "proxyscope.application.journal",
            "proxyscope.application.actions",
            "proxyscope.application.events.EventBus",
            "proxyscope.application.events.bus.EventBus",
        )
        paths = [PACKAGE_ROOT / "application" / "commands" / "runtime_registry.py"]
        paths.extend((PACKAGE_ROOT / "application" / "components").rglob("*.py"))
        paths.extend((PACKAGE_ROOT / "components").rglob("*.py"))
        violations = {
            (_module_name(path), imported)
            for path in paths
            for imported in _absolute_imports(path)
            if imported.startswith(forbidden_prefixes)
        }
        self.assertEqual(violations, set(), f"Components depend on application implementations: {sorted(violations)}")

    def test_features_do_not_import_application(self) -> None:
        violations = {
            (_module_name(path), imported)
            for path in (PACKAGE_ROOT / "components").rglob("*.py")
            for imported in _absolute_imports(path)
            if imported.startswith(("proxyscope.application.", "proxyscope.bootstrap."))
        }
        self.assertEqual(violations, set())

    def test_contracts_do_not_import_implementations(self) -> None:
        violations = {
            (_module_name(path), imported)
            for path in (PACKAGE_ROOT / "contracts").rglob("*.py")
            for imported in _absolute_imports(path)
            if imported.startswith(
                ("proxyscope.application.", "proxyscope.adapters.", "proxyscope.components.", "proxyscope.bootstrap.")
            )
        }
        self.assertEqual(violations, set())

    def test_application_proxy_does_not_depend_on_transport_technology(self) -> None:
        forbidden_prefixes = ("http.server", "requests", "socket", "ssl", "selectors")
        violations: set[tuple[str, str]] = set()
        for path in (PACKAGE_ROOT / "application" / "proxy").rglob("*.py"):
            source_module = _module_name(path)
            for imported_module in _absolute_imports(path):
                if imported_module.startswith(forbidden_prefixes):
                    violations.add((source_module, imported_module))

        self.assertEqual(violations, set(), f"Application proxy depends on transport technology: {sorted(violations)}")

    def test_proxy_server_streams_through_forwarding_port(self) -> None:
        source = (PACKAGE_ROOT / "adapters" / "proxy" / "server.py").read_text(encoding="utf-8")

        self.assertIn("StreamingForwarder", source)
        self.assertNotIn("isinstance(server.forwarder, UpstreamForwarder)", source)

    def test_application_and_adapter_tests_do_not_import_proxy_forwarding_models(self) -> None:
        forbidden_prefixes = (
            "proxyscope.adapters.proxy.forwarding",
            "proxyscope.adapters.proxy.upstream.forwarding.ForwardRequest",
            "proxyscope.adapters.proxy.upstream.forwarding.ForwardResponse",
        )
        violations: set[tuple[str, str]] = set()
        for test_dir in (PROJECT_ROOT / "tests" / "application", PROJECT_ROOT / "tests" / "adapters"):
            for path in test_dir.rglob("*.py"):
                source_module = _module_name(path)
                for imported_module in _absolute_imports(path):
                    if imported_module.startswith(forbidden_prefixes):
                        violations.add((source_module, imported_module))

        self.assertEqual(violations, set(), f"Tests import proxy forwarding models: {sorted(violations)}")

    def test_packages_define_at_most_five_direct_classes(self) -> None:
        violations: dict[str, list[str]] = {}
        package_dirs = {path.parent for path in PACKAGE_ROOT.rglob("*.py") if "__pycache__" not in path.parts}
        for package_dir in package_dirs:
            classes: list[str] = []
            for path in package_dir.glob("*.py"):
                classes.extend(f"{path.name}:{class_name}" for class_name in _top_level_classes(path))
            limit = MAX_CLASSES_PER_PACKAGE_OVERRIDES.get(
                str(package_dir.relative_to(PROJECT_ROOT)), MAX_CLASSES_PER_PACKAGE
            )
            if len(classes) > limit:
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
