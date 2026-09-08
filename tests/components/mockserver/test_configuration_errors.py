import pytest

from proxyscope.components.mockserver import MockResponse, mockserver_configuration_from_payload


@pytest.mark.parametrize(
    "payload",
    [
        {"unknown": True},
        {"scenarios": {}},
        {"scenarios": [1]},
        {"scenarios": [{"id": ""}]},
        {"scenarios": [{"id": "demo", "enabled": 1}]},
        {"scenarios": [{"id": "demo", "responses": [1]}]},
        {"scenarios": [{"id": "demo"}, {"id": "demo"}]},
    ],
)
def test_invalid_scenario_configuration_is_rejected(payload):
    with pytest.raises(ValueError):
        mockserver_configuration_from_payload(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"headers": []},
        {"headers": {"name": 1}},
        {"headers": {1: "value"}},
        {"status": True},
        {"status": "200"},
        {"status": 99},
        {"status": 600},
        {"body": []},
        {"unknown": True},
        {"method": " "},
        {"url": ""},
    ],
)
def test_invalid_mock_response_configuration_is_rejected(changes):
    response = {"id": "r", "method": "GET", "url": "http://api.test", **changes}
    with pytest.raises(ValueError):
        mockserver_configuration_from_payload({"scenarios": [{"id": "demo", "responses": [response]}]})


def test_duplicate_response_ids_within_scenario_are_rejected():
    response = {"id": "r", "method": "GET", "url": "http://api.test"}
    with pytest.raises(ValueError, match="unique within a scenario"):
        mockserver_configuration_from_payload({"scenarios": [{"id": "demo", "responses": [response, response]}]})


@pytest.mark.parametrize("values", [("", "GET", "http://api.test"), ("r", "", "http://api.test"), ("r", "GET", "")])
def test_mock_response_requires_identity_method_and_url(values):
    with pytest.raises(ValueError, match="must not be empty"):
        MockResponse(*values)
