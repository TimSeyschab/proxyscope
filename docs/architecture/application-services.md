# Application Services

`proxyscope.application` exposes surface-independent use cases for requests,
policies, sessions and exports, and runtime settings. The Textual UI is an
adapter: it talks to `RuntimeUIController`, which delegates behavior to an
injected `RuntimeApplicationServices` bundle.

## Command Registry

Top-level commands are declared as `CommandDefinition` values with a canonical
name, aliases, handler, usage, and help text. `CommandRegistry` generates
dispatch, the short command summary, and the detailed command help.

Adding a top-level command requires registering one definition. It does not
require another branch in the controller or changes to Textual components.

## Future REST API

A REST adapter can construct or receive the same `RuntimeApplicationServices`
bundle and map HTTP endpoints to its methods. It should translate transport
payloads and application results at the boundary, without importing Textual or
reimplementing policy, request, session, or settings behavior.

The Protocol contracts in `proxyscope.application.contracts` define the stable
surface for additional adapters and test doubles.
