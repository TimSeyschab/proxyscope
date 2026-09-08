import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from proxyscope.application.configuration import parse_config_payload, serialize_config_document
from proxyscope.components.mockserver.configuration import (
    mockserver_configuration_from_payload,
    mockserver_configuration_payload,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("variant", ["minimal", "maximal"])
def test_configuration_examples_match_schemas_and_roundtrip(variant: str) -> None:
    payload = json.loads((PROJECT_ROOT / "examples" / f"runtime-config.{variant}.json").read_text(encoding="utf-8"))
    runtime_schema = json.loads((PROJECT_ROOT / "schemas" / "runtime-config.schema.json").read_text(encoding="utf-8"))
    runtime_validator = Draft202012Validator(runtime_schema)
    runtime_validator.validate(payload)

    document = parse_config_payload(payload)
    serialized = serialize_config_document(document)

    runtime_validator.validate(serialized)
    assert parse_config_payload(serialized) == document

    mock_payload = document.components.configuration_for("mockserver")
    if mock_payload is not None:
        mock_schema = json.loads(
            (PROJECT_ROOT / "proxyscope" / "components" / "mockserver" / "config.schema.json").read_text(
                encoding="utf-8"
            )
        )
        mock_validator = Draft202012Validator(mock_schema)
        mock_validator.validate(mock_payload)
        store = mockserver_configuration_from_payload(mock_payload)
        serialized_mocks = mockserver_configuration_payload(store)
        mock_validator.validate(serialized_mocks)
        assert mockserver_configuration_from_payload(serialized_mocks).list_scenarios() == store.list_scenarios()
