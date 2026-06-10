#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   POETRY_PYPI_TOKEN_PYPI="pypi-..." ./scripts/publish_pypi.sh
# or configure once:
#   poetry config pypi-token.pypi "pypi-..."

if ! command -v poetry >/dev/null 2>&1; then
  echo "poetry not found in PATH" >&2
  exit 1
fi

if [[ -z "${POETRY_PYPI_TOKEN_PYPI:-}" ]]; then
  echo "POETRY_PYPI_TOKEN_PYPI is not set."
  echo "Set it for this shell or run: poetry config pypi-token.pypi <token>"
fi

poetry check
poetry run ruff format --check proxyscope tests scripts
poetry run ruff check proxyscope tests scripts
poetry run pyright
poetry run coverage run -m unittest discover -s tests -p "test_*.py"
poetry run coverage report
poetry build
poetry publish --no-interaction
