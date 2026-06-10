# Policy Processing

## Current Flow

Runtime policies are stored and evaluated by `RuntimeConfig`. Plain HTTP and
MITM traffic currently query this state through separate processing paths:

```text
Plain HTTP: RequestLoggingHandler -> RuntimeConfig -> forward/static/edit
MITM HTTP: MitmTLSInterceptor -> response rewriter -> RuntimeConfig -> edit/static
```

Policy actions are currently represented by string values such as
`open_editor` and `static_response`.

## Target Flow

A transport-independent policy engine evaluates a request once and returns a
typed decision:

```text
RequestContext -> PolicyEngine -> Forward | StaticResponse | EditResponse
```

Transport adapters must not know concrete policy types. Adding a policy type
should require a domain model, serialization support, and a handler, but no
changes to HTTP or MITM adapters.

## Invariants

- Policy matching is deterministic and priority ordered.
- Invalid action/template combinations cannot be represented.
- Policy evaluation has no filesystem, UI, or network side effects.
- Serialization and migration are separate from policy evaluation.
