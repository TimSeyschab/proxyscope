from collections.abc import Callable

from proxyscope.contracts.events import RuntimeEvent
from proxyscope.contracts.ports import ComponentEventBus
from proxyscope.contracts.traffic_rules import TrafficRule, serialize_rule
from proxyscope.contracts.traffic_rules.events import (
    TrafficRuleScopeUpdateRequested,
    TrafficRulesResult,
    TrafficRulesSnapshotRequested,
    TrafficRulesUpdateRequested,
)

from .store import TrafficRuleStore


class TrafficRuleEventHandler:
    def __init__(
        self,
        store: TrafficRuleStore,
        event_bus: ComponentEventBus,
        *,
        on_change: Callable[[tuple[dict[str, object], ...]], None] | None = None,
    ) -> None:
        self._store = store
        self._event_bus = event_bus
        self._on_change = on_change

    def __call__(self, event: RuntimeEvent) -> None:
        if not isinstance(
            event, (TrafficRulesUpdateRequested, TrafficRuleScopeUpdateRequested, TrafficRulesSnapshotRequested)
        ):
            return
        error = None
        try:
            if isinstance(event, TrafficRulesUpdateRequested):
                self._store.apply_update(event, before_commit=self._persist if event.persist else None)
            elif isinstance(event, TrafficRuleScopeUpdateRequested):
                self._store.set_scope(event.scope)
        except (ValueError, OSError) as exc:
            error = str(exc)
        self._event_bus.publish(
            TrafficRulesResult(
                correlation_id=event.event_id,
                rules=self._store.snapshot(),
                error=error,
            )
        )

    def _persist(self, rules: tuple[TrafficRule, ...]) -> None:
        if self._on_change is not None:
            self._on_change(tuple(serialize_rule(rule) for rule in rules))
