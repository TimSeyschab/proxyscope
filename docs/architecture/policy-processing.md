# Policy Processing

## Current Flow

Runtime policies are stored behind a `PolicyRepository` and evaluated by the
transport-independent `PolicyEngine`. `RuntimeConfig` still coordinates policy
mutation and config-file persistence until Phase 4, but it does not evaluate
requests.

```text
Plain HTTP: RequestLoggingHandler -> PolicyEngine -> forward/static/edit
MITM HTTP: MitmTLSInterceptor -> response rewriter -> PolicyEngine -> edit/static
```

Policy actions are represented by `OpenEditorAction` and
`StaticResponseAction`. The action type owns all required state, so invalid
action/template combinations cannot be represented.

## Target Flow

A transport-independent policy engine evaluates a request and returns a typed
`PolicyEvaluation`:

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
