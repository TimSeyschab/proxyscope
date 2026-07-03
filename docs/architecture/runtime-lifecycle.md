# Runtime Lifecycle

## Current Lifecycle

`proxyscope.app.main` parses CLI options and delegates to the explicit
composition root:

```python
with ProxyApplication(ApplicationOptions(...)) as application:
    application.run()
```

`ProxyApplication` lives in `proxyscope.app.application` and owns lifecycle
coordination: enter, logging setup, server thread start, UI execution, shutdown,
and cleanup. `proxyscope.app.composition.create_runtime_object_graph()` creates
the runtime object graph: config, journal, application services, processing
runtime, server, and optional MITM interceptor. `proxyscope.adapters.factory`
injects concrete editor, replay, and session adapters into the application
services.

Runtime settings, policy administration, and configuration persistence are
constructed separately. No aggregate runtime-config facade participates in the
composition.

Headless and TUI modes start the same managed server thread and use the same
shutdown path. The application layer itself does not import `proxyscope.app`,
`proxyscope.adapters`, or Textual.

## Lifecycle Rules

- Construction does not mutate process-global service state.
- Headless mode does not import Textual.
- Shutdown stops accepting requests before releasing dependencies.
- Shutdown closes active tunnels, cancels pending edits, closes the server, and
  joins the server thread.
- Pending interactive edits have a configurable timeout, fall back to the
  original response, and are cancelled on shutdown.
- Logging setup and restoration belong to the application lifecycle.
- Tests can create and stop multiple independent application instances.
