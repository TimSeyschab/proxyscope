# Configuration

## Current Schema

Configuration files use `schema_version: 1` and separate runtime settings from
canonical typed policies:

```text
ConfigRepository
  -> migrations
  -> validation and serialization
  -> ConfigDocument(RuntimeSettings, PolicyRule[])
```

`JsonConfigRepository` writes atomically through a temporary file followed by
`os.replace`. Legacy files without `schema_version` are accepted and converted
to the current schema on the next save.

## Policy Shortcuts

`policy_shortcuts` is an input-only convenience syntax for demos and replay
setups. It supports:

- `match: "<METHOD> <URL>"`;
- a trailing `*` for prefix matching;
- `action: "open_editor"`;
- static `respond.body` or structured `respond.json`.

Shortcuts are parsed into normal typed policies. Saving always emits canonical
`policies`, so the domain and runtime do not need a second policy model.

## Validation

Unknown fields, wrong primitive types, unsupported schema versions, malformed
shortcut matches, and invalid policies produce field-specific errors. Invalid
values are not silently ignored.
