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
| `proxyscope.application` | Surface-independent request, policy, session/export, settings, and command use cases | Domain modules and injected adapter contracts |
| `proxyscope.proxy` | Plain HTTP, CONNECT, and HTTP/1 framing adapters | Processing models and injected ports |
| `proxyscope.mitm` | TLS interception transport adapter | Processing models, proxy framing adapters, certificates, and injected ports |
| `proxyscope.policies` | Policy models, matching, evaluation, serialization, and repository ports | Policy-local modules only |
| `proxyscope.config` | Versioned settings, validation, migrations, and config repository | Config-local modules and policy serialization |
| `proxyscope.app.runtime` | Textual controller, presenters, navigation, and compatibility adapters | Application services and UI-local modules |
| `proxyscope.app.config` | Mutable runtime facade for settings and policy administration | Config domain and policy repository |
| `proxyscope.app.editing` | External-editor integration and pending response edits | Processing response models |
| `proxyscope.app.logging` | Exchange recording and runtime logging | Injected journal and logging policy |

## Enforced Dependency Rules

Imports from `proxyscope.proxy` or `proxyscope.mitm` into `proxyscope.app` are
forbidden. The policy, config, and processing domains may not depend on app,
proxy, or MITM adapters. These rules are enforced by
`tests/architecture/test_import_boundaries.py`.

## Composition Root

`proxyscope.app.main` is the current composition root. It may construct concrete
implementations and connect adapters to application services. Other modules
should receive dependencies explicitly instead of reading global service
locators.
