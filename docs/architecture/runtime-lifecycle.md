# Runtime Lifecycle

## Current Lifecycle

`proxyscope.app.main` is the composition root. It creates runtime config,
journal, response modifier, exchange recorder, and runtime event dispatcher,
assembles them in a `ProxyRuntimeContext`, and injects that context into the
proxy server and MITM interceptor.

Runtime services are instance-local. Multiple proxy servers can run in one
process with isolated policies, journals, response transformers, and event
sinks.

## Target Lifecycle

The composition root will create an explicit application runtime:

```python
with ProxyApplication(options) as application:
    application.run()
```

The runtime owns server threads, injected services, logging configuration,
pending edits, and deterministic shutdown.

## Lifecycle Rules

- Construction does not mutate process-global service state.
- Headless mode does not import Textual.
- Shutdown stops accepting requests before releasing dependencies.
- Pending interactive edits have a timeout and are cancelled on shutdown.
- Tests can create and stop multiple independent application instances.
