import ast
from importlib.util import resolve_name


def imported_names(source: str, *, module: str, is_package: bool = False) -> set[str]:
    """Resolve static imports without importing or executing the inspected code."""
    package = module if is_package else module.rpartition(".")[0]
    imports: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            target = "." * node.level + (node.module or "")
            if node.level:
                target = resolve_name(target, package)
            imports.update(f"{target}.{alias.name}" for alias in node.names)
    return imports


def matches_module(name: str, module: str) -> bool:
    return name == module or name.startswith(module + ".")
