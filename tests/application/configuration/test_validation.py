import pytest

from proxyscope.application.configuration import ConfigValidationError, parse_config_payload, serialize_config_document


@pytest.mark.parametrize(
    ("section", "value", "message"),
    [
        ("settings", None, "settings must be"),
        ("settings", {"extra": 1}, "unknown field"),
        ("settings", {"log_level": "BOGUS"}, "unsupported value"),
        ("settings", {"log_level": " "}, "non-empty string"),
        ("settings", {"mitm_enabled": 1}, "must be a boolean"),
        ("settings", {"log_whitelist": "api.test"}, "array of strings"),
        ("settings", {"log_whitelist": [1]}, "array of strings"),
        ("event_store", [], "must be a JSON object"),
        ("event_store", {"queue_size": True}, "must be an integer"),
        ("event_store", {"max_events": 0}, "greater than zero"),
        ("event_store", {"max_body_bytes": "10"}, "must be an integer"),
        ("components", [], "must be a JSON object"),
        ("components", {"enabled": "core"}, "array of non-empty strings"),
        ("components", {"enabled": [""]}, "array of non-empty strings"),
        ("components", {"configurations": []}, "must be a JSON object"),
        ("components", {"configurations": {" Core ": {}}}, "normalized component IDs"),
        ("components", {"configurations": {1: {}}}, "normalized component IDs"),
        ("components", {"configurations": {"core": []}}, "must be a JSON object"),
        ("components", {"configurations": {"core": {"bad": {1, 2}}}}, "must contain JSON values"),
        ("components", {"configurations": {"core": {1: "bad"}}}, "must contain JSON values"),
        ("traffic_rules", {}, "array of objects"),
        ("traffic_rules", [1], "array of objects"),
        ("traffic_rules", [{}], "traffic_rules\\[0\\] is invalid"),
    ],
)
def test_rejects_invalid_configuration_at_field_boundary(section, value, message):
    payload = {"schema_version": 1, "settings": {}, section: value}
    with pytest.raises(ConfigValidationError, match=message):
        parse_config_payload(payload)


@pytest.mark.parametrize("payload", [None, [], "config", {"schema_version": 2, "settings": {}}])
def test_rejects_invalid_root_and_schema_version(payload):
    with pytest.raises(ConfigValidationError):
        parse_config_payload(payload)


def test_nested_component_payload_roundtrips_all_json_value_types():
    configuration = {"nested": [{"flag": True, "number": 1.5, "null": None}, "value", 2]}
    payload = {
        "schema_version": 1,
        "settings": {},
        "components": {
            "enabled": [" CORE ", "core", "mockserver"],
            "configurations": {"mockserver": configuration},
        },
    }
    document = parse_config_payload(payload)
    assert document.components.enabled_components == ("core", "mockserver")
    assert document.components.configuration_for("mockserver") == configuration
    assert parse_config_payload(serialize_config_document(document)) == document
