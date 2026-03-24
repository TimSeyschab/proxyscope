# proxyscope

`proxyscope` is an interactive HTTP/HTTPS proxy for request inspection, response editing, static-response policies, and live runtime control in a terminal UI.

## Highlights

- Forward HTTP requests through an upstream connection.
- Handle HTTPS via `CONNECT` and optional TLS interception (MITM).
- Group request/response logs by request id.
- Inspect request/response details in a TUI.
- Edit matching responses in an external editor.
- Persist runtime configuration and policy rules.
- Replay captured requests.

## Requirements

- Python `3.13+`
- Poetry `2.x`

## Installation

```bash
poetry install
```

## Run

```bash
poetry run proxyscope --host 127.0.0.1 --port 8080
```

With persisted runtime configuration:

```bash
poetry run proxyscope --config ./runtime-config.json
```

Without TUI:

```bash
poetry run proxyscope --no-ui
```

## Runtime Commands (TUI)

- `help`
- `clear`
- `sites`
- `loglevel <DEBUG|INFO|WARNING|ERROR>`
- `filter [show|clear|host|method|status|text] ...`
- `find <text>|clear`
- `export <json|har> <path>`
- `session <save|load> <path>`
- `mitm [show|on|off|certs-dir <path>]`
- `whitelist [show|add|remove|clear] ...`
- `cache [show|on|off|toggle]`
- `config [show|save [path]|reload]`
- `policy [show|add-editor|add-editor-prefix|remove-editor|clear-editor|add-static|add-static-prefix|set-priority|edit|remove|enable|disable] ...`
- `quit`

## Keyboard Shortcuts (TUI)

- `Left` / `Right`: Focus zwischen Panels wechseln.
- `Up` / `Down`: Auswahl bewegen oder vertikal scrollen (abhängig vom aktiven Panel).
- `PageUp` / `PageDown`: Schnelles vertikales Scrollen.
- `Enter`: Request-Detail für den ausgewählten Request öffnen (oder Kommando ausführen, wenn Eingabezeile befüllt ist).
- `Enter` im `Policies`-Tab: Ausgewählte Policy im externen Editor öffnen.
- `Backspace`: Zeichen in der Kommandozeile löschen.
- `Tab` / `Shift+Tab`: Vorwärts oder rückwärts durch Requests, Detail-Tabs, Sidebar-Tabs und Kommandozeile wechseln.
- `Shift+B`: Request-Detail schließen, zurück zur Request-Liste.
- `Shift+S`: Rechtes Panel auf `Sites` schalten; bei erneutem Drücken im `Sites`-Tab wird die Sidebar ausgeblendet.
- `Shift+P`: Rechtes Panel auf `Policies` schalten.
- `Shift+M`: Ausgewählten Request als Editor-Policy (`METHOD + URL`) hinzufügen.
- `Shift+R`: Ausgewählten Request editieren und erneut senden.
- `Shift+A`: Ausgewählte Site zur Log-Whitelist hinzufügen (`Sites`-Tab).
- `Shift+D`: Ausgewählte Policy deaktivieren (`Policies`-Tab).
- `Shift+E`: Ausgewählte Policy aktivieren (`Policies`-Tab).
- `Shift+I`: Ausgewählte Policy bearbeiten (`Policies`-Tab).
- `Shift+U`: Ausgewählte Site aus der Log-Whitelist entfernen (`Sites`-Tab).
- `Shift+X`: Ausgewählte Policy entfernen (`Policies`-Tab).

Hinweis: Buchstaben-Shortcuts werden nur als Shift-Kombination verarbeitet (`Shift+M` entspricht `M`).

## TLS Interception (MITM)

On startup, proxyscope now auto-creates local CA materials under `certs/ca` if they are missing.
Import `certs/ca/mitm-ca.crt` into your browser trust store for local testing.

To regenerate CA files, delete the existing cert material and restart proxyscope:

```bash
rm -f certs/ca/mitm-ca.key.pem certs/ca/mitm-ca.cert.pem certs/ca/mitm-ca.crt certs/ca/mitm-ca.cnf certs/hosts/*.pem certs/hosts/*.srl
```

## Tests

```bash
poetry run python -m unittest discover -s tests -p "test_*.py" -v
```

## Release / Publish

### 1. Bump Version

```bash
poetry version patch
# or: poetry version minor / poetry version major
```

### 2. Validate + Build

```bash
poetry check
poetry build
```

### 3. Configure PyPI Token

Either use an environment variable:

```bash
export POETRY_PYPI_TOKEN_PYPI="pypi-..."
```

or persistent Poetry config:

```bash
poetry config pypi-token.pypi "pypi-..."
```

### 4. Publish to PyPI

```bash
poetry publish --no-interaction
```

Alternative:

```bash
./scripts/publish_pypi.sh
```

### 5. Install from PyPI (verification)

```bash
pip install proxyscope
```

## License

MIT. See [LICENSE](LICENSE).
