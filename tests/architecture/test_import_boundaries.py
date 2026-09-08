import ast
from pathlib import Path

import pytest

from tests.support.imports import imported_names, matches_module

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "proxyscope"
MAX_CLASSES_PER_PACKAGE = 5
MAX_CLASSES_PER_PACKAGE_OVERRIDES = {
    # Event and traffic-rule packages intentionally expose cohesive type families.
    "proxyscope/application/configuration": 8,
    "proxyscope/contracts/events": 20,
    "proxyscope/contracts/traffic_rules": 12,
}


@pytest.mark.parametrize(
    ("roots", "forbidden"),
    [
        pytest.param(
            ("proxyscope/adapters/proxy", "proxyscope/adapters/mitm"),
            ("proxyscope.bootstrap",),
            id="transport-does-not-import-bootstrap",
        ),
        pytest.param(
            ("proxyscope/adapters/proxy",),
            ("proxyscope.adapters.mitm",),
            id="proxy-does-not-construct-mitm",
        ),
        pytest.param(
            ("proxyscope/application",),
            ("textual", "proxyscope.bootstrap", "proxyscope.adapters", "proxyscope.components"),
            id="application-does-not-import-outer-layers",
        ),
        pytest.param(
            ("proxyscope/application/components",),
            ("textual", "proxyscope.adapters", "proxyscope.bootstrap", "proxyscope.proxy"),
            id="component-contracts-do-not-import-outer-layers",
        ),
        pytest.param(
            ("proxyscope/application/commands/handlers",),
            ("proxyscope.application.commands.handlers",),
            id="command-handlers-do-not-import-siblings",
        ),
        pytest.param(
            (
                "proxyscope/application/commands/runtime_registry.py",
                "proxyscope/application/components",
                "proxyscope/components",
            ),
            (
                "proxyscope.application.services",
                "proxyscope.application.journal",
                "proxyscope.application.actions",
                "proxyscope.application.events.EventBus",
                "proxyscope.application.events.bus.EventBus",
            ),
            id="components-use-ports",
        ),
        pytest.param(
            ("proxyscope/components",),
            ("proxyscope.application", "proxyscope.bootstrap"),
            id="features-do-not-import-application",
        ),
        pytest.param(
            ("proxyscope/contracts",),
            ("proxyscope.application", "proxyscope.adapters", "proxyscope.components", "proxyscope.bootstrap"),
            id="contracts-do-not-import-implementations",
        ),
        pytest.param(
            ("proxyscope/application/proxy",),
            ("http.server", "requests", "socket", "ssl", "selectors"),
            id="application-proxy-does-not-import-transport-technology",
        ),
        pytest.param(
            ("tests/application", "tests/adapters"),
            (
                "proxyscope.adapters.proxy.forwarding",
                "proxyscope.adapters.proxy.upstream.forwarding.ForwardRequest",
                "proxyscope.adapters.proxy.upstream.forwarding.ForwardResponse",
            ),
            id="tests-use-exchange-contracts",
        ),
    ],
)
def test_import_boundaries(roots: tuple[str, ...], forbidden: tuple[str, ...]) -> None:
    violations: set[tuple[str, str]] = set()
    for root in roots:
        root_path = PROJECT_ROOT / root
        assert root_path.exists(), f"Architecture scope does not exist: {root}"
        paths = (root_path,) if root_path.is_file() else root_path.rglob("*.py")
        for path in paths:
            module_parts = path.relative_to(PROJECT_ROOT).with_suffix("").parts
            is_package = path.name == "__init__.py"
            module = ".".join(module_parts[:-1] if is_package else module_parts)
            imports = imported_names(path.read_text(encoding="utf-8"), module=module, is_package=is_package)
            violations.update(
                (str(path.relative_to(PROJECT_ROOT)), imported)
                for imported in imports
                if any(matches_module(imported, prefix) for prefix in forbidden)
            )
    assert not violations, f"Forbidden imports: {sorted(violations)}"


def test_proxy_server_streams_through_forwarding_port() -> None:
    source = (PACKAGE_ROOT / "adapters" / "proxy" / "server.py").read_text(encoding="utf-8")
    assert "StreamingForwarder" in source
    assert "isinstance(server.forwarder, UpstreamForwarder)" not in source


def test_packages_define_at_most_five_direct_classes() -> None:
    violations: dict[str, list[str]] = {}
    package_dirs = {path.parent for path in PACKAGE_ROOT.rglob("*.py")}
    for package_dir in package_dirs:
        classes: list[str] = []
        for path in package_dir.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            classes.extend(f"{path.name}:{node.name}" for node in tree.body if isinstance(node, ast.ClassDef))
        package = str(package_dir.relative_to(PROJECT_ROOT))
        limit = MAX_CLASSES_PER_PACKAGE_OVERRIDES.get(package, MAX_CLASSES_PER_PACKAGE)
        if len(classes) > limit:
            violations[package] = sorted(classes)
    assert not violations, f"Packages exceed their direct class limit: {violations}"
