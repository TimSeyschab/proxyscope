"""Dynamic component registration and lifecycle management."""

from .manager import (
    CORE_COMPONENT_ID,
    ComponentContext,
    ComponentContribution,
    ComponentManager,
    ComponentRegistry,
    normalize_component_id,
)
from .ports import CapturedExchange, CapturedResponse, ComponentEventBus, ComponentJournal

__all__ = [
    "CapturedExchange",
    "CapturedResponse",
    "ComponentEventBus",
    "ComponentJournal",
    "CORE_COMPONENT_ID",
    "ComponentContext",
    "ComponentContribution",
    "ComponentManager",
    "ComponentRegistry",
    "normalize_component_id",
]
