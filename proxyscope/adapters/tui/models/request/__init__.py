from dataclasses import dataclass


@dataclass(frozen=True)
class RequestRowModel:
    request_id: int
    cells: tuple[str, str, str, str, str, str]


@dataclass(frozen=True)
class RequestListModel:
    title: str
    rows: list[RequestRowModel]
    cursor: int
    row_offset: int
    follow_top: bool
    selected_request_id: int | None
