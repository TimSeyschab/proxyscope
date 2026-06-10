# Module Boundaries

## Intended Dependency Direction

Dependencies point inward toward stable contracts and domain models:

```text
adapters -> ports -> application -> domain
```

## Current Modules

| Module | Responsibility | May depend on |
| --- | --- | --- |
| `proxyscope.processing` | Transport-independent exchange models, middleware ports, and shared pipeline | Processing-local modules only |
| `proxyscope.application` | Surface-independent use cases, runtime configuration, request journal, and pending response edits | Domain modules and injected adapter contracts |
| `proxyscope.adapters.tui` | Textual UI, controller, presentation models, navigation, and components | Application services and TUI-local modules |
| `proxyscope.adapters.editing` | External-editor adapters for policies and responses | Application models and policy serialization |
| `proxyscope.adapters.replay` | Network and editor adapter for request replay | Application request journal |
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

Imports from `proxyscope.proxy` or `proxyscope.mitm` into `proxyscope.app` are
forbidden. The policy, config, and processing domains may not depend on app,
proxy, or MITM adapters. The application layer may not depend on `app`,
`adapters`, or Textual; concrete adapter functions are injected by the adapter
factory. These rules are enforced by
`tests/architecture/test_import_boundaries.py`.

## Composition Root

`proxyscope.app.application.ProxyApplication` owns the lifecycle, while
`proxyscope.app.composition` and `proxyscope.adapters.factory` connect concrete
adapters to application services. Other modules receive dependencies explicitly
instead of reading global service locators.
