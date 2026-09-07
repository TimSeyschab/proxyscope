from dataclasses import dataclass


@dataclass(frozen=True)
class TabbedListTabModel:
    key: str
    title: str
    items: list[str]
    cursor: int
    empty_label: str = "<empty>"


@dataclass(frozen=True)
class TabbedListModel:
    tabs: list[TabbedListTabModel]
    active_key: str
