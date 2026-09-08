from dataclasses import dataclass
from typing import Self

from proxyscope.application.journal import LoggedExchange


@dataclass(frozen=True)
class RequestWindow:
    entries: list[LoggedExchange]
    offset: int
    total_count: int
    all_count: int
    selected_entry: LoggedExchange | None

    @classmethod
    def from_entries(cls, entries: list[LoggedExchange], *, cursor: int, limit: int, all_count: int) -> Self:
        total_count = len(entries)
        selected_index = min(max(cursor, 0), total_count - 1) if entries else None
        window_size = max(0, limit)
        offset = 0
        if selected_index is not None and window_size > 0:
            last_offset = max(0, total_count - window_size)
            offset = min(max(selected_index - window_size // 2, 0), last_offset)
        return cls(
            entries=entries[offset : offset + window_size],
            offset=offset,
            total_count=total_count,
            all_count=all_count,
            selected_entry=None if selected_index is None else entries[selected_index],
        )
