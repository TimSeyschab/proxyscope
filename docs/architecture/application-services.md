# Application Services

`proxyscope.application` exposes surface-independent use cases for requests,
policies, sessions and exports, runtime settings, runtime views, commands,
replay, and response-edit actions. The Textual UI is an adapter:
`RuntimeCLI` owns the logging-handler and UI-facing methods, `RuntimeController`
owns TUI navigation and selection state, and both delegate behavior to an
injected `RuntimeApplicationServices` bundle. The Textual app consumes the
TUI-local `RuntimeUIController` Protocol rather than individual application
state services.

Adapter-side action functions are grouped in `RuntimeApplicationAdapters` before
they are passed to `create_runtime_application_services()`. This keeps service
construction stable when editor, replay, or session adapters evolve.

## Command Registry

Top-level commands are declared as `CommandDefinition` values with a canonical
name, aliases, handler, usage, and help text. `CommandRegistry` owns dispatch,
alias lookup, the short command summary, and the detailed command help.

Adding a top-level command requires registering one definition. It does not
require another branch in the controller or changes to Textual components.
Top-level runtime commands are registered through feature-oriented provider
functions in `commands/runtime_registry.py` (`_help_commands`,
`_request_commands`, `_session_commands`, `_runtime_subcommands`, and
`_shutdown_commands`) and then composed by `create_runtime_command_registry()`.

Runtime subcommands are grouped by application feature:

- `commands/handlers/policy.py` owns policy command parsing and policy mutations.
- `commands/handlers/settings.py` owns log level, whitelist, cache, and MITM commands.
- `commands/handlers/config.py` owns config show/save/reload commands.
- `commands/runtime_service.py` remains the small parser/dispatcher for runtime
  subcommands and delegates to feature handlers.

Command handlers return `commands/runtime_result.py` results so
side effects that need adapter cooperation, such as log-level updates, cache
tunnel cleanup, or scheduling the policy editor, stay explicit at the boundary.

## Future REST API

A REST adapter can construct or receive the same `RuntimeApplicationServices`
bundle and map HTTP endpoints to its methods. It should translate transport
payloads and application results at the boundary, without importing Textual or
reimplementing policy, request, session, or settings behavior.

The Protocol contracts in `proxyscope.application.contracts` define the stable
surface for additional adapters and test doubles.
