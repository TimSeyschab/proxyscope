# proxyscope

`proxyscope` is an HTTP/HTTPS debugging proxy with shared traffic processing
and optional runtime components.

## Capabilities

- HTTP forwarding, HTTPS tunnels, and optional TLS interception with a local CA.
- Traffic rules for static responses, header changes, and body rewrites.
- Mock scenarios backed by the shared traffic-rule engine.
- Application services for captured traffic, response editing, replay, and session export.
- Runtime events with optional persistent history.

Interactive editing and command dispatch require an integrating frontend; the
CLI does not expose an interactive command prompt.

## Install And Run

Development requires Python 3.13 or newer (below 4.0) and Poetry 2.x.
From the repository root:

```bash
poetry install
poetry run proxyscope --host 127.0.0.1 --port 8080
```

For available startup options, use the CLI help:

```bash
poetry run proxyscope --help
```

Point a client at the proxy:

```bash
curl -x http://127.0.0.1:8080 http://example.com/
```

Stop the CLI with Ctrl+C.

Enable the read-only terminal view in the runtime configuration, then start
the proxy normally:

```bash
poetry run proxyscope --config ./runtime-config.json
```

The TUI is an optional read-only runtime component. Add `tui` to
`components.enabled` to activate it. It projects captured
exchanges from the journal and runtime notifications from the event bus; it
does not read configuration or traffic-rule services directly.

## Configuration

Load a JSON runtime configuration with `--config`:

```bash
poetry run proxyscope --config ./runtime-config.json
```

A minimal configuration is:

```json
{
  "schema_version": 1,
  "settings": {}
}
```

Ready-to-run files are available as
[minimal configuration](examples/runtime-config.minimal.json) and
[complete configuration](examples/runtime-config.maximal.json).

Only the current configuration format is supported; there is no automatic legacy
migration. Static responses belong to traffic rules. Mock scenarios define their
own static responses, which the mockserver projects to runtime traffic rules.

`traffic_rules` and `event_store` are global runtime concerns and therefore
live at the configuration root. `components` only contains activation and
component-owned configuration payloads.

The [configuration package](proxyscope/application/configuration) defines the
runtime validation, defaults, and persistence. The machine-readable
[JSON Schema](schemas/runtime-config.schema.json) describes the canonical file
format. `components.configurations` reserves a JSON-object payload for each
component; each component owns the syntax of its own payload. Mockserver
scenarios belong in `components.configurations.mockserver`, as described by its
[component schema](proxyscope/components/mockserver/config.schema.json). See the
[traffic-rule tests](tests/application/traffic_rules/test_traffic_rule_service.py)
for executable examples. Changes made through services that save configuration
are persisted when a configuration path is attached.

For example, a mockserver scenario is configured as:

```json
{
  "components": {
    "configurations": {
      "mockserver": {
        "scenarios": [
          {
            "id": "offline",
            "name": "Offline API",
            "enabled": false,
            "responses": [
              {"id": "health", "method": "GET", "url": "https://api.example.test/health", "status": 503, "body": "offline"}
            ]
          }
        ]
      }
    }
  }
}
```

## HTTPS Interception

For TLS interception, the client must trust the generated root certificate at
`<mitm_certs_dir>/ca/mitm-ca.crt`. Certificate material is created when MITM is
initialized. Use `--mitm off` to run HTTPS tunnels without interception.

## Architecture

See [Architecture](docs/architecture/README.md) for module responsibilities,
dependency boundaries, request processing, and component integration.

## Development Checks

The test suite contains both unittest-style and pytest-style tests; use pytest
to run the complete suite. It is included in the Poetry development dependencies.

```bash
poetry run python -m pytest tests
poetry run ruff check proxyscope tests scripts
poetry run pyright
```

CI measures both statements and branches. The combined coverage and the separate
branch coverage must each reach 81%. Branch coverage checks decision outcomes;
it does not establish full condition coverage or MC/DC for compound expressions.
The tests include independent cases for compound conditions in request filters,
configuration validation, and response editing.

```bash
poetry run coverage run -m pytest tests -q
poetry run coverage report
poetry run coverage json -o coverage.json
poetry run python scripts/check_branch_coverage.py coverage.json
poetry run coverage html
```

The HTML report is written to `htmlcov/index.html`.

Architecture boundaries are checked in
[tests/architecture](tests/architecture). The
[CI workflow](.github/workflows/ci.yml) defines the automation currently in use.

## License

MIT, see [LICENSE](LICENSE).
