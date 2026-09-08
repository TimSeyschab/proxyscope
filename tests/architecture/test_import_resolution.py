import pytest

from tests.support.imports import imported_names, matches_module


@pytest.mark.parametrize(
    ("source", "module", "is_package", "expected"),
    [
        ("import socket as transport", "proxyscope.application.service", False, {"socket"}),
        ("from proxyscope import adapters", "proxyscope.application.service", False, {"proxyscope.adapters"}),
        ("from ..adapters import proxy", "proxyscope.application.service", False, {"proxyscope.adapters.proxy"}),
        ("from .. import adapters", "proxyscope.application.service", False, {"proxyscope.adapters"}),
        ("from ..adapters import proxy", "proxyscope.application", True, {"proxyscope.adapters.proxy"}),
        (
            "from . import engine",
            "proxyscope.application.traffic_rules",
            True,
            {"proxyscope.application.traffic_rules.engine"},
        ),
        ("from socket import *", "proxyscope.application.service", False, {"socket.*"}),
        ("def f():\n    import ssl", "proxyscope.application.service", False, {"ssl"}),
    ],
)
def test_resolves_static_imports(source, module, is_package, expected):
    assert imported_names(source, module=module, is_package=is_package) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [("socket", True), ("socket.socket", True), ("socketserver", False)],
)
def test_module_matching_respects_package_boundaries(name, expected):
    assert matches_module(name, "socket") is expected
