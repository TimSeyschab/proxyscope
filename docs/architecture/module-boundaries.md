# Module Boundaries

## Intended Dependency Direction

Dependencies point inward toward stable contracts and domain models:

```text
adapters -> ports -> application -> domain
```

## Current Modules

| Module | Responsibility | May depend on |
| --- | --- | --- |
| `proxyscope.proxy` | Plain HTTP and CONNECT transport adapters | Proxy-local models and injected ports |
| `proxyscope.mitm` | TLS interception transport adapter | Proxy-local models, certificates, and injected ports |
| `proxyscope.policies` | Policy models, matching, evaluation, serialization, and repository ports | Policy-local modules only |
| `proxyscope.app.runtime` | Runtime use cases, commands, and UI coordination | Config, editing, logging, and UI contracts |
| `proxyscope.app.config` | Current settings and transitional config-file persistence | Config-local modules and policy repository |
| `proxyscope.app.editing` | External-editor integration and pending response edits | Injected policy evaluator and proxy response models |
| `proxyscope.app.logging` | Exchange recording and runtime logging | Injected journal and logging policy |

## Enforced Transitional Rule

New imports from `proxyscope.proxy` or `proxyscope.mitm` into
`proxyscope.app` are forbidden. Existing imports are recorded as temporary
exceptions in `tests/architecture/test_import_boundaries.py`.

Phase 2 removes these exceptions by introducing an explicit runtime context and
small Protocol-based ports.

## Composition Root

`proxyscope.app.main` is the current composition root. It may construct concrete
implementations and connect adapters to application services. Other modules
should receive dependencies explicitly instead of reading global service
locators.
