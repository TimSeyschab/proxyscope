from .service import MockScenarioStore, scenario_store_from_config


def mockserver_configuration_from_payload(payload: dict[str, object] | None) -> MockScenarioStore:
    if payload is None:
        return MockScenarioStore()
    unknown = sorted(set(payload) - {"scenarios"})
    if unknown:
        raise ValueError(f"Mockserver configuration contains unknown field(s): {', '.join(unknown)}.")
    scenarios = payload.get("scenarios", [])
    if not isinstance(scenarios, list) or not all(isinstance(item, dict) for item in scenarios):
        raise ValueError("Mockserver scenarios must be an array of objects.")
    return scenario_store_from_config(tuple(dict(item) for item in scenarios))


def mockserver_configuration_payload(store: MockScenarioStore) -> dict[str, object]:
    return {"scenarios": list(store.serialize())}
