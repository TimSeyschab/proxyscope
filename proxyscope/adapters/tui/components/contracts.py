from dataclasses import dataclass


@dataclass(frozen=True)
class ComponentId:
    value: str


@dataclass(frozen=True)
class FocusTargetId:
    value: str


@dataclass(frozen=True)
class ComponentFocus:
    component_id: ComponentId
    target_id: FocusTargetId
    pane_key: str

    @property
    def key(self) -> str:
        return f"{self.component_id.value}:{self.target_id.value}"


TRAFFIC_COMPONENT_ID = ComponentId("traffic")
ADMIN_COMPONENT_ID = ComponentId("admin")

REQUESTS_FOCUS = ComponentFocus(
    component_id=TRAFFIC_COMPONENT_ID,
    target_id=FocusTargetId("requests"),
    pane_key="requests",
)


def detail_focus(tab_key: str) -> ComponentFocus:
    return ComponentFocus(
        component_id=TRAFFIC_COMPONENT_ID,
        target_id=FocusTargetId(f"detail:{tab_key}"),
        pane_key="detail",
    )


def admin_tab_focus(tab_key: str) -> ComponentFocus:
    return ComponentFocus(
        component_id=ADMIN_COMPONENT_ID,
        target_id=FocusTargetId(tab_key),
        pane_key=tab_key,
    )
