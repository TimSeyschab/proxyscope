# Architecture

proxyscope is moving toward a pragmatic hexagonal architecture. Domain and
application behavior should remain independent from transport adapters, terminal
UI code, and persistence details.

## Target Layers

```text
UI / CLI / future APIs (`proxyscope.adapters`)
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
processing. `proxyscope.app` is limited to startup, lifecycle, and composition.
Architecture tests keep the application and domain packages independent from
outer adapters.

## Documents

- [Module Boundaries](module-boundaries.md)
- [Policy Processing](policy-processing.md)
- [Application Services](application-services.md)
- [Runtime Lifecycle](runtime-lifecycle.md)
- [Configuration](../configuration.md)
