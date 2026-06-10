# Policy Processing

## Current Flow

Runtime policies are stored behind a `PolicyRepository` and evaluated by the
transport-independent `PolicyEngine`. `PolicyAdministrationService` coordinates
mutable policy administration, while `RuntimeConfigurationService` owns
config-file persistence and migration. Mutating application use cases
explicitly orchestrate persistence.

```text
Plain HTTP: RequestLoggingHandler -> ExchangePipeline -> forward/static/edit
MITM HTTP: MitmTLSInterceptor -> ExchangePipeline -> upstream response/static/edit
```

Policy actions are represented by `OpenEditorAction` and
`StaticResponseAction`. The action type owns all required state, so invalid
action/template combinations cannot be represented.

## Processing Flow

`ExchangePipeline` owns the shared request and response processing. It evaluates
policies through the injected policy port without exposing policy types to the
transport adapters:

```text
ExchangeRequest
  -> request middleware
  -> policy evaluation
  -> static response or transport forwarding
  -> response transformation and middleware
  -> exchange recording
```

Plain HTTP and MITM construct the same transport-independent exchange models.
HTTP/1 stream rewriters only parse and rebuild framing; they delegate cache
header rewriting and response processing to the pipeline.

## Invariants

- Policy matching is deterministic and priority ordered.
- Invalid action/template combinations cannot be represented.
- Policy evaluation has no filesystem, UI, or network side effects.
- Serialization and migration are separate from policy evaluation.
