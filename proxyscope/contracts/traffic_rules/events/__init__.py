from dataclasses import dataclass, field
from typing import Literal

from proxyscope.contracts.events import RuntimeEvent
from proxyscope.contracts.traffic_rules import TrafficRule


@dataclass(frozen=True)
class TrafficRuleScope:
    owner_id: str
    rule_ids: tuple[str, ...]
    active_rule_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.owner_id.strip():
            raise ValueError("Rule scope owner must not be empty.")
        if not set(self.active_rule_ids).issubset(self.rule_ids):
            raise ValueError("Active rule IDs must belong to the scope.")


@dataclass(frozen=True, kw_only=True)
class TrafficRulesUpdateRequested(RuntimeEvent):
    operation: Literal["add", "replace", "remove", "replace_all"]
    rules: tuple[TrafficRule, ...] = ()
    rule_ids: tuple[str, ...] = ()
    scope: TrafficRuleScope | None = None
    persist: bool = True
    event_type: str = field(init=False, default="traffic_rules.update_requested")


@dataclass(frozen=True, kw_only=True)
class TrafficRuleScopeUpdateRequested(RuntimeEvent):
    scope: TrafficRuleScope
    event_type: str = field(init=False, default="traffic_rules.scope_update_requested")


@dataclass(frozen=True, kw_only=True)
class TrafficRulesSnapshotRequested(RuntimeEvent):
    event_type: str = field(init=False, default="traffic_rules.snapshot_requested")


@dataclass(frozen=True, kw_only=True)
class TrafficRulesResult(RuntimeEvent):
    correlation_id: str
    rules: tuple[TrafficRule, ...]
    error: str | None = None
    event_type: str = field(init=False, default="traffic_rules.result")
