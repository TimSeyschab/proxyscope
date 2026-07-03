# Module Boundaries

## Intended Dependency Direction

Most dependencies point inward toward stable contracts and domain models. The
composition root is the deliberate exception: `proxyscope.app` imports concrete
adapters so the rest of the system does not need service locators or hidden
global state.

```text
app -> concrete adapters
adapters -> application services and processing ports
application -> policies, config, and injected action contracts
processing -> processing-local models and ports
policies/config -> package-local domain code
```

## Current Modules

| Module | Responsibility | May depend on |
| --- | --- | --- |
| `proxyscope.processing` | Transport-independent exchange models, middleware, HTTP/runtime ports, and shared pipeline | Processing-local modules only |
| `proxyscope.application` | Surface-independent use cases, runtime configuration, request journal, and pending response edits | Domain modules and injected adapter contracts |
| `proxyscope.adapters` | Adapter factory that binds concrete editor, replay, and session adapters to application action contracts | Concrete adapter subpackages and application services |
| `proxyscope.adapters.tui` | Textual UI, controller, presentation models, navigation, and components | Application services and TUI-local modules |
| `proxyscope.adapters.editing` | External-editor adapters for policies and responses | Application models and policy serialization |
| `proxyscope.adapters.replay` | Network and editor adapter for request replay | Application actions and request journal models |
| `proxyscope.adapters.sessions` | JSON and HAR session serialization | Application request journal |
| `proxyscope.adapters.observability` | Exchange recording, runtime events, and logging setup | Application runtime state and processing models |
| `proxyscope.proxy` | Plain HTTP, CONNECT, and HTTP/1 framing adapters | Processing models and injected ports |
| `proxyscope.mitm` | TLS interception transport adapter | Processing models, proxy framing adapters, certificates, and injected ports |
| `proxyscope.policies` | Policy models, matching, evaluation, serialization, and repository ports | Policy-local modules only |
| `proxyscope.config` | Versioned settings, validation, migrations, and config repository | Config-local modules and policy serialization |
| `proxyscope.app` | Executable entry point, application lifecycle, and composition root | All concrete adapters required for composition |

## Runtime Configuration

Runtime configuration is split into three application-level responsibilities:

- `RuntimeSettingsState` owns thread-safe mutable runtime settings without file
  system access.
- `PolicyAdministrationService` owns policy administration over an injected
  policy repository.
- `RuntimeConfigurationService` translates both states to and from
  `ConfigDocument` and owns config repository access.

There is no aggregate runtime-config facade. Composition injects the three
responsibilities separately. Mutating application use cases explicitly call
`RuntimeConfigurationService.save()` after successful settings or policy
changes; reads and failed mutations do not trigger hidden file I/O.

## Enforced Dependency Rules

`proxyscope.proxy` and `proxyscope.mitm` must not import `proxyscope.app`.
`proxyscope.proxy` also must not construct or import the MITM adapter. The
policy, config, and processing domains may not depend on app, proxy, or MITM
adapters. The application layer may not depend on `app`, `adapters`, or Textual;
concrete adapter functions are injected by the adapter factory. TUI runtime
entrypoints consume the `RuntimeApplicationServices` bundle instead of bypassing
it to individual state services. These rules are enforced by
`tests/architecture/test_import_boundaries.py`.

Packages should stay small enough to keep ownership obvious. A production
package may define at most five direct classes across its immediate Python
modules; if a package needs more, split it into subpackages with narrower
responsibilities and expose a small facade from `__init__.py` when compatibility
or ergonomics require it. This is enforced by the same architecture test suite.

## Composition Root

`proxyscope.app.application.ProxyApplication` owns lifecycle coordination.
`proxyscope.app.composition.create_runtime_object_graph()` builds the runtime
object graph, including config, state, application services, proxy processing
context, server, and optional MITM interceptor. `proxyscope.adapters.factory`
connects concrete editor, replay, and session adapters to application services.
Other modules receive dependencies explicitly instead of reading global service
locators.
