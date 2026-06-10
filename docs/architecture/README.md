# Architecture

proxyscope is moving toward a pragmatic hexagonal architecture. Domain and
application behavior should remain independent from transport adapters, terminal
UI code, and persistence details.

## Target Layers

```text
UI / CLI / future APIs
        |
Application services
        |
Policy and exchange-processing domain
        |
Ports
        |
HTTP, MITM, Textual, filesystem, and network adapters
```

The current architecture still contains transitional dependencies from
`proxyscope.proxy` and `proxyscope.mitm` into `proxyscope.app`. These are
documented and guarded by an architecture test so they can be removed
incrementally without allowing new dependencies.

## Documents

- [Module Boundaries](module-boundaries.md)
- [Policy Processing](policy-processing.md)
- [Runtime Lifecycle](runtime-lifecycle.md)
- [Refactoring Roadmap](../architecture-refactoring-plan.md)
