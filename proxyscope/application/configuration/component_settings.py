from dataclasses import dataclass


@dataclass(frozen=True)
class ComponentSettings:
    enabled_components: tuple[str, ...] = ("core",)
    configurations: tuple[tuple[str, dict[str, object]], ...] = ()

    def configuration_for(self, component_id: str) -> dict[str, object] | None:
        return next((dict(value) for identifier, value in self.configurations if identifier == component_id), None)


__all__ = ["ComponentSettings"]
