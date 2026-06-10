# Runtime Lifecycle

## Current Lifecycle

`proxyscope.app.main` currently:

1. parses startup options;
2. creates runtime config, journal, and response modifier services;
3. installs global service locators;
4. creates and starts the proxy server;
5. optionally creates the Textual UI;
6. coordinates shutdown.

This works for one process-wide proxy instance, but global state limits test
isolation, parallel instances, and additional frontends.

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
