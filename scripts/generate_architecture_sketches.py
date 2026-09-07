from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "proxyscope"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "architecture" / "program-architecture.md"


@dataclass(frozen=True)
class ModuleGroup:
    key: str
    prefixes: tuple[str, ...]
    label: str
    description: str
    debt: str


MODULE_GROUPS = (
    ModuleGroup(
        key="bootstrap",
        prefixes=("proxyscope.bootstrap",),
        label="proxyscope.bootstrap",
        description="Executable entry point, lifecycle coordination, runtime object graph creation, and composition.",
        debt=(
            "Lifecycle orchestration is now separated from object graph creation. The remaining risk is that "
            "RuntimeObjectGraph can become a broad change hotspot if new adapters are added without small contracts."
        ),
    ),
    ModuleGroup(
        key="adapters",
        prefixes=("proxyscope.adapters.factory",),
        label="proxyscope.adapters",
        description="Adapter factory that binds concrete adapter functions to application action contracts.",
        debt=(
            "Adapter actions now cross into application services as RuntimeApplicationAdapters. Keep that bundle cohesive "
            "so it does not become a generic service locator."
        ),
    ),
    ModuleGroup(
        key="adapters_tui",
        prefixes=("proxyscope.adapters.tui",),
        label="proxyscope.adapters.tui",
        description="Textual runtime UI, controller, presenter, navigation state, view models, and reusable components.",
        debt=(
            "The TUI is split into many focused packages. Keep entrypoints behind RuntimeApplicationServices so view "
            "components do not start depending on individual state services."
        ),
    ),
    ModuleGroup(
        key="adapters_editing",
        prefixes=("proxyscope.adapters.editing",),
        label="proxyscope.adapters.editing",
        description="External-editor integration for policy editing and pending response editing.",
        debt="Editor round trips are adapter side effects; keep parsing and validation in application/domain services.",
    ),
    ModuleGroup(
        key="adapters_replay",
        prefixes=("proxyscope.adapters.replay",),
        label="proxyscope.adapters.replay",
        description="Request replay adapter that edits and resends logged requests through the configured proxy base URL.",
        debt="Replay currently depends on requests-style network behavior; future async transports may need a new adapter.",
    ),
    ModuleGroup(
        key="adapters_sessions",
        prefixes=("proxyscope.adapters.sessions",),
        label="proxyscope.adapters.sessions",
        description="JSON and HAR session import/export for recorded request journal entries.",
        debt="Session formats are adapter concerns; avoid leaking format-specific fields into journal models.",
    ),
    ModuleGroup(
        key="adapters_observability",
        prefixes=("proxyscope.adapters.observability",),
        label="proxyscope.adapters.observability",
        description="Request/response recording, runtime event dispatch, and logging configuration.",
        debt="Observability bridges processing events into application state; keep this boundary thin to avoid hidden policy.",
    ),
    ModuleGroup(
        key="application",
        prefixes=("proxyscope.application",),
        label="proxyscope.application",
        description="Surface-independent use cases for requests, policies, sessions, settings, commands, and response edits.",
        debt="Command handling is feature-oriented now; resist adding adapter-specific behavior to command handlers.",
    ),
    ModuleGroup(
        key="config",
        prefixes=("proxyscope.config",),
        label="proxyscope.config",
        description="Versioned runtime settings schema, config serialization, migrations, validation, and JSON repository.",
        debt="Schema versioning is in place; every new config field should get migration and validation coverage.",
    ),
    ModuleGroup(
        key="policies",
        prefixes=("proxyscope.policies",),
        label="proxyscope.policies",
        description="Policy models, matching, priority ordering, serialization, repository protocol, and in-memory store.",
        debt="Policy evaluation is deterministic; keep side effects in application/adapters to preserve testability.",
    ),
    ModuleGroup(
        key="processing",
        prefixes=("proxyscope.processing",),
        label="proxyscope.processing",
        description="Transport-independent exchange models, middleware, processing ports, and shared exchange pipeline.",
        debt="Processing ports are the main cross-layer contract; broadening them too much would couple transports again.",
    ),
    ModuleGroup(
        key="proxy",
        prefixes=("proxyscope.proxy",),
        label="proxyscope.proxy",
        description="Plain HTTP proxy server, CONNECT tunnel handling, upstream forwarding, and HTTP/1 framing helpers.",
        debt=(
            "Compatibility wrapper modules such as proxy/http1_*.py should remain temporary or documented as public API."
        ),
    ),
    ModuleGroup(
        key="mitm",
        prefixes=("proxyscope.mitm",),
        label="proxyscope.mitm",
        description="TLS interception adapter, local CA management, forged host certificates, and decrypted HTTP/1 relay.",
        debt=(
            "MITM relay, sniffing, and response rewriting are concentrated in the tunnel adapter. HTTP/2 support or richer "
            "stream processing would need a clearer internal split."
        ),
    ),
)

GROUP_BY_KEY = {group.key: group for group in MODULE_GROUPS}


def main() -> None:
    edges = _collect_group_edges()
    markdown = _render_markdown(edges)
    OUTPUT_PATH.write_text(markdown, encoding="utf-8")


def _collect_group_edges() -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for path in PACKAGE_ROOT.rglob("*.py"):
        source_group = _group_for_module(_module_name(path))
        if source_group is None:
            continue
        for imported_module in _absolute_imports(path):
            target_group = _group_for_module(imported_module)
            if target_group is None or target_group == source_group:
                continue
            edges.add((source_group, target_group))
    return edges


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("proxyscope"))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            if node.module.startswith("proxyscope"):
                imports.add(node.module)
    return imports


def _module_name(path: Path) -> str:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    return ".".join(relative.parts)


def _group_for_module(module_name: str) -> str | None:
    best_match: tuple[int, str] | None = None
    for group in MODULE_GROUPS:
        for prefix in group.prefixes:
            if module_name == prefix or module_name.startswith(f"{prefix}."):
                match = (len(prefix), group.key)
                if best_match is None or match[0] > best_match[0]:
                    best_match = match
    return None if best_match is None else best_match[1]


def _render_markdown(edges: set[tuple[str, str]]) -> str:
    sections = [
        "# Program Architecture Sketch",
        "",
        "This document is generated by `scripts/generate_architecture_sketches.py`.",
        "Regenerate it after architecture-relevant code changes:",
        "",
        "```bash",
        "poetry run python scripts/generate_architecture_sketches.py",
        "```",
        "",
        "## Import Dependency Sketch",
        "",
        "The graph is derived from absolute `proxyscope.*` imports. Runtime dependencies passed as callables or Protocol "
        "implementations are documented in the following sketches.",
        "",
        "```mermaid",
        *_render_import_graph(edges),
        "```",
        "",
        "## Runtime Composition Sketch",
        "",
        "```mermaid",
        *_runtime_composition_graph(),
        "```",
        "",
        "## Request Processing Sketch",
        "",
        "```mermaid",
        *_request_processing_sequence(),
        "```",
        "",
        "## Module Notes",
        "",
        *_module_table(edges),
        "",
        "## Potential Technical Debt",
        "",
        *_technical_debt_list(),
        "",
    ]
    return "\n".join(sections)


def _render_import_graph(edges: set[tuple[str, str]]) -> list[str]:
    lines = ["flowchart LR"]
    for group in MODULE_GROUPS:
        lines.append(f'    {group.key}["{group.label}"]')
    for source, target in sorted(edges, key=lambda edge: (_group_index(edge[0]), _group_index(edge[1]))):
        lines.append(f"    {source} --> {target}")
    return lines


def _runtime_composition_graph() -> list[str]:
    return [
        "flowchart TD",
        '    bootstrap_cli["proxyscope.bootstrap.cli<br/>CLI parsing"]',
        '    bootstrap_lifecycle["ProxyApplication<br/>lifecycle and shutdown"]',
        '    runtime_graph["RuntimeObjectGraph<br/>explicit composed dependencies"]',
        '    config_repo["JsonConfigRepository<br/>ConfigDocument"]',
        '    runtime_state["RuntimeSettingsState<br/>PolicyAdministrationService<br/>RequestJournal<br/>ResponseModifierService"]',
        '    app_services["RuntimeApplicationServices<br/>surface-independent use cases"]',
        '    proxy_context["ProxyRuntimeContext<br/>PolicyEngine + ExchangePipeline + Recorder"]',
        '    proxy_server["ProxyHTTPServer<br/>plain HTTP and CONNECT"]',
        '    mitm_adapter["MitmTLSInterceptor<br/>optional TLS interception"]',
        '    tui_adapter["RuntimeCLI / Textual<br/>optional UI adapter"]',
        "    bootstrap_cli --> bootstrap_lifecycle",
        "    bootstrap_lifecycle --> runtime_graph",
        "    runtime_graph --> config_repo",
        "    runtime_graph --> runtime_state",
        "    runtime_state --> app_services",
        "    runtime_state --> proxy_context",
        "    proxy_context --> proxy_server",
        "    proxy_context --> mitm_adapter",
        "    app_services --> tui_adapter",
        "    runtime_graph --> proxy_server",
        "    bootstrap_lifecycle --> tui_adapter",
    ]


def _request_processing_sequence() -> list[str]:
    return [
        "sequenceDiagram",
        "    participant Client",
        "    participant Proxy as ProxyHTTPServer / MITM",
        "    participant Pipeline as ExchangePipeline",
        "    participant Policies as PolicyEngine",
        "    participant Upstream",
        "    participant Recorder as RequestResponseRecorder",
        "    Client->>Proxy: HTTP request or decrypted HTTPS request",
        "    Proxy->>Pipeline: prepare_request(ExchangeRequest)",
        "    Pipeline->>Recorder: record_request(...)",
        "    Pipeline->>Policies: evaluate method + URL",
        "    alt static response policy",
        "        Pipeline-->>Proxy: PreparedExchange with static response",
        "    else upstream forwarding",
        "        Proxy->>Upstream: forward or stream request",
        "        Upstream-->>Proxy: response",
        "    end",
        "    Proxy->>Pipeline: process_response(...)",
        "    opt open_editor policy",
        "        Pipeline->>Pipeline: response transformer edits response",
        "    end",
        "    Pipeline->>Recorder: record_response(...)",
        "    Pipeline-->>Proxy: final response",
        "    Proxy-->>Client: final response bytes",
    ]


def _module_table(edges: set[tuple[str, str]]) -> list[str]:
    lines = [
        "| Module | Description | Observed dependencies |",
        "| --- | --- | --- |",
    ]
    for group in MODULE_GROUPS:
        targets = [GROUP_BY_KEY[target].label for source, target in edges if source == group.key]
        dependency_text = ", ".join(f"`{target}`" for target in sorted(targets)) or "None inside `proxyscope`"
        lines.append(f"| `{group.label}` | {group.description} | {dependency_text} |")
    return lines


def _technical_debt_list() -> list[str]:
    return [f"- `{group.label}`: {group.debt}" for group in MODULE_GROUPS]


def _group_index(key: str) -> int:
    for index, group in enumerate(MODULE_GROUPS):
        if group.key == key:
            return index
    return len(MODULE_GROUPS)


if __name__ == "__main__":
    main()
