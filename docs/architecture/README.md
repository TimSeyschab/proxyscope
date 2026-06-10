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

The transport-independent `proxyscope.processing` package owns shared exchange
processing. Architecture tests keep policy, config, and processing domains
independent from app, proxy, and MITM adapters.

## Documents

- [Module Boundaries](module-boundaries.md)
- [Policy Processing](policy-processing.md)
- [Runtime Lifecycle](runtime-lifecycle.md)
- [Refactoring Roadmap](../architecture-refactoring-plan.md)
