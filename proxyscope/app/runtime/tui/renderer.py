from dataclasses import dataclass
import curses
from typing import Literal

from proxyscope.app.runtime.journal import LoggedExchange

MainMode = Literal["requests", "request_detail"]
ActivePane = Literal["requests", "detail", "aux"]
DetailTab = Literal["request", "response"]


@dataclass(frozen=True)
class AuxPanelTabModel:
    key: str
    title: str
    items: list[str]
    cursor: int
    scroll: int
    empty_label: str = "<empty>"


@dataclass(frozen=True)
class RuntimeScreenModel:
    request_entries: list[LoggedExchange]
    request_cursor: int
    request_scroll: int
    request_detail_scroll: int
    response_detail_scroll: int
    main_mode: MainMode
    active_pane: ActivePane
    detail_tab: DetailTab
    aux_visible: bool
    aux_tabs: list[AuxPanelTabModel]
    aux_active_key: str
    command_buffer: str
    status_message: str
    config_text: str


@dataclass(frozen=True)
class RuntimeScreenResult:
    aux_scrolls: dict[str, int]
    request_scroll: int
    request_detail_scroll: int
    response_detail_scroll: int


class RuntimeScreenRenderer:
    def __init__(self) -> None:
        self._colors_initialized = False

    def draw(self, stdscr: "curses._CursesWindow", model: RuntimeScreenModel) -> RuntimeScreenResult:
        self._init_colors()
        stdscr.erase()
        rows, cols = stdscr.getmaxyx()
        if rows < 18 or cols < 90:
            _safe_addnstr(stdscr, 0, 0, "Terminal too small for runtime UI.", max(1, cols - 1), curses.A_BOLD)
            stdscr.refresh()
            return RuntimeScreenResult(
                aux_scrolls={tab.key: tab.scroll for tab in model.aux_tabs},
                request_scroll=model.request_scroll,
                request_detail_scroll=model.request_detail_scroll,
                response_detail_scroll=model.response_detail_scroll,
            )

        command_height = 6
        content_height = rows - command_height
        aux_width = _compute_aux_width(cols, model.aux_visible)
        main_width = cols - aux_width - (1 if aux_width > 0 else 0)

        request_scroll = model.request_scroll
        request_detail_scroll = model.request_detail_scroll
        response_detail_scroll = model.response_detail_scroll
        aux_scrolls = {tab.key: tab.scroll for tab in model.aux_tabs}

        if model.main_mode == "requests":
            request_scroll = _draw_requests_pane(
                stdscr,
                row=0,
                col=0,
                height=content_height,
                width=main_width,
                entries=model.request_entries,
                cursor=model.request_cursor,
                scroll=model.request_scroll,
                active=model.active_pane == "requests",
                selected_attr=self._selected_attr(),
            )
        else:
            request_area_width = _compute_request_list_width(
                total_main_width=main_width,
                aux_visible=model.aux_visible,
            )
            detail_area_width = main_width - request_area_width - 1
            request_scroll = _draw_requests_pane(
                stdscr,
                row=0,
                col=0,
                height=content_height,
                width=request_area_width,
                entries=model.request_entries,
                cursor=model.request_cursor,
                scroll=model.request_scroll,
                active=model.active_pane == "requests",
                selected_attr=self._selected_attr(),
            )
            selected_entry = model.request_entries[model.request_cursor] if model.request_entries else None
            request_detail_scroll, response_detail_scroll = _draw_detail_pane(
                stdscr,
                row=0,
                col=request_area_width + 1,
                height=content_height,
                width=detail_area_width,
                entry=selected_entry,
                active=model.active_pane == "detail",
                active_tab=model.detail_tab,
                request_scroll=model.request_detail_scroll,
                response_scroll=model.response_detail_scroll,
                selected_attr=self._selected_attr(),
            )

        if aux_width > 0:
            if model.main_mode == "request_detail":
                _safe_addch(stdscr, 0, main_width, "|")
                for y in range(1, content_height):
                    _safe_addch(stdscr, y, main_width, "|")
            aux_scrolls = _draw_aux_panel(
                stdscr,
                row=0,
                col=main_width + 1,
                height=content_height,
                width=aux_width,
                tabs=model.aux_tabs,
                active_key=model.aux_active_key,
                active=model.active_pane == "aux",
                selected_attr=self._selected_attr(),
            )

        _draw_command_area(
            stdscr,
            top=content_height,
            width=cols,
            command_buffer=model.command_buffer,
            config_text=model.config_text,
            status_message=model.status_message,
            title_attr=self._title_attr(),
            status_attr=self._status_attr(),
        )
        cursor_col = min(cols - 2, len(model.command_buffer) + 4)
        try:
            stdscr.move(content_height + 2, cursor_col)
        except curses.error:
            pass
        stdscr.refresh()

        return RuntimeScreenResult(
            aux_scrolls=aux_scrolls,
            request_scroll=request_scroll,
            request_detail_scroll=request_detail_scroll,
            response_detail_scroll=response_detail_scroll,
        )

    def _init_colors(self) -> None:
        if self._colors_initialized:
            return
        if not curses.has_colors():
            self._colors_initialized = True
            return
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
            curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)
        except curses.error:
            pass
        self._colors_initialized = True

    def _title_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(1) | curses.A_BOLD
        return curses.A_BOLD

    def _status_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(2) | curses.A_BOLD
        return curses.A_REVERSE

    def _selected_attr(self) -> int:
        if curses.has_colors():
            return curses.color_pair(3) | curses.A_BOLD
        return curses.A_REVERSE


def _draw_requests_pane(
    stdscr: "curses._CursesWindow",
    *,
    row: int,
    col: int,
    height: int,
    width: int,
    entries: list[LoggedExchange],
    cursor: int,
    scroll: int,
    active: bool,
    selected_attr: int,
) -> int:
    title = "REQUESTS"
    if active:
        title += " *"
    _draw_box(stdscr, row, col, height, width, title, active=active)
    inner_height = max(0, height - 2)
    inner_width = max(1, width - 2)
    normalized_scroll = _ensure_visible(cursor, scroll, inner_height)
    visible = entries[normalized_scroll: normalized_scroll + inner_height]
    for row_offset, entry in enumerate(visible):
        absolute_index = normalized_scroll + row_offset
        selected = absolute_index == cursor and active
        marker = ">" if selected else " "
        status = "---" if entry.response is None else str(entry.response.status_code)
        host = entry.target_host or "-"
        duration = "-" if entry.duration_ms is None else f"{entry.duration_ms:.1f}ms"
        row_text = (
            f"{marker}{entry.request_id:4d} {status:>3} "
            f"{entry.request.method:<7} {host:<20} {entry.request.path} [{duration}]"
        )
        attr = selected_attr if selected else 0
        _safe_addnstr(
            stdscr,
            row + 1 + row_offset,
            col + 1,
            _fit_text(row_text, inner_width),
            inner_width,
            attr,
        )
    return normalized_scroll


def _draw_detail_pane(
    stdscr: "curses._CursesWindow",
    *,
    row: int,
    col: int,
    height: int,
    width: int,
    entry: LoggedExchange | None,
    active: bool,
    active_tab: DetailTab,
    request_scroll: int,
    response_scroll: int,
    selected_attr: int,
) -> tuple[int, int]:
    title = f"DETAIL [{active_tab}]"
    if active:
        title += " *"
    _draw_box(stdscr, row, col, height, width, title, active=active)
    inner_height = max(0, height - 2)
    inner_width = max(1, width - 2)
    if entry is None:
        _safe_addnstr(stdscr, row + 1, col + 1, "No request selected.", inner_width, 0)
        return request_scroll, response_scroll

    request_tab = "[REQUEST]"
    response_tab = "[RESPONSE]"
    request_attr = selected_attr if active and active_tab == "request" else curses.A_BOLD
    response_attr = selected_attr if active and active_tab == "response" else curses.A_BOLD
    _safe_addnstr(stdscr, row + 1, col + 1, request_tab, min(len(request_tab), inner_width), request_attr)
    if inner_width > len(request_tab) + 1:
        _safe_addnstr(
            stdscr,
            row + 1,
            col + 1 + len(request_tab) + 1,
            response_tab,
            min(len(response_tab), inner_width - len(request_tab) - 1),
            response_attr,
        )

    content_row = row + 2
    content_height = max(0, inner_height - 1)
    if content_height == 0:
        return request_scroll, response_scroll

    request_lines = _build_request_lines(entry, inner_width)
    response_lines = _build_response_lines(entry, inner_width)
    request_max_scroll = max(0, len(request_lines) - content_height)
    response_max_scroll = max(0, len(response_lines) - content_height)
    request_scroll = min(max(0, request_scroll), request_max_scroll)
    response_scroll = min(max(0, response_scroll), response_max_scroll)

    lines = request_lines if active_tab == "request" else response_lines
    scroll = request_scroll if active_tab == "request" else response_scroll
    visible = lines[scroll: scroll + content_height]
    for row_offset, line in enumerate(visible):
        _safe_addnstr(stdscr, content_row + row_offset, col + 1, _fit_text(line, inner_width), inner_width, 0)
    return request_scroll, response_scroll


def _draw_aux_panel(
    stdscr: "curses._CursesWindow",
    *,
    row: int,
    col: int,
    height: int,
    width: int,
    tabs: list[AuxPanelTabModel],
    active_key: str,
    active: bool,
    selected_attr: int,
) -> dict[str, int]:
    title = "UTILITY [Shift+V hide]"
    if active:
        title += " *"
    _draw_box(stdscr, row, col, height, width, title, active=active)

    inner_width = max(1, width - 2)
    inner_height = max(0, height - 2)
    if not tabs:
        _safe_addnstr(stdscr, row + 1, col + 1, "<no tabs>", inner_width, 0)
        return {}

    tab_col = col + 1
    max_col = col + inner_width
    for tab in tabs:
        label = f"[{tab.title}]"
        remaining = max_col - tab_col + 1
        if remaining <= 1:
            break
        attr = selected_attr if active and tab.key == active_key else curses.A_BOLD
        _safe_addnstr(stdscr, row + 1, tab_col, label, remaining, attr)
        tab_col += len(label) + 1

    content_row = row + 2
    content_height = max(0, inner_height - 1)
    if content_height == 0:
        return {tab.key: tab.scroll for tab in tabs}

    selected_tab = next((tab for tab in tabs if tab.key == active_key), tabs[0])
    normalized = _ensure_visible(selected_tab.cursor, selected_tab.scroll, content_height)
    visible = selected_tab.items[normalized: normalized + content_height]
    if not visible:
        _safe_addnstr(
            stdscr,
            content_row,
            col + 1,
            _fit_text(selected_tab.empty_label, inner_width),
            inner_width,
            0,
        )
    for row_offset, item in enumerate(visible):
        absolute_index = normalized + row_offset
        selected = absolute_index == selected_tab.cursor and active
        marker = ">" if selected else " "
        row_text = f"{marker}{absolute_index + 1:3d}. {item}"
        attr = selected_attr if selected else 0
        _safe_addnstr(stdscr, content_row + row_offset, col + 1, _fit_text(row_text, inner_width), inner_width, attr)
    updated = {tab.key: tab.scroll for tab in tabs}
    updated[selected_tab.key] = normalized
    return updated


def _draw_command_area(
    stdscr: "curses._CursesWindow",
    *,
    top: int,
    width: int,
    command_buffer: str,
    config_text: str,
    status_message: str,
    title_attr: int,
    status_attr: int,
) -> None:
    for col_idx in range(width):
        _safe_addch(stdscr, top, col_idx, "-")
    _safe_addnstr(stdscr, top + 1, 1, "COMMAND", max(1, width - 2), title_attr)
    _safe_addnstr(stdscr, top + 2, 1, _safe_text(f"> {command_buffer}"), max(1, width - 2), 0)
    _safe_addnstr(stdscr, top + 3, 1, _fit_text(_safe_text(f"CONFIG: {config_text}"), max(1, width - 2)), max(1, width - 2), 0)
    _safe_addnstr(stdscr, top + 4, 1, _fit_text(_safe_text(status_message), max(1, width - 2)), max(1, width - 2), status_attr)


def _draw_box(
    stdscr: "curses._CursesWindow",
    row: int,
    col: int,
    height: int,
    width: int,
    title: str,
    *,
    active: bool,
) -> None:
    if height < 2 or width < 2:
        return
    bottom = row + height - 1
    right = col + width - 1
    _safe_addch(stdscr, row, col, "+")
    _safe_addch(stdscr, row, right, "+")
    _safe_addch(stdscr, bottom, col, "+")
    _safe_addch(stdscr, bottom, right, "+")
    for x in range(col + 1, right):
        _safe_addch(stdscr, row, x, "-")
        _safe_addch(stdscr, bottom, x, "-")
    for y in range(row + 1, bottom):
        _safe_addch(stdscr, y, col, "|")
        _safe_addch(stdscr, y, right, "|")
    attr = curses.A_BOLD | (curses.A_REVERSE if active else 0)
    _safe_addnstr(stdscr, row, col + 2, _fit_text(f"[ {title} ]", max(1, width - 4)), max(1, width - 4), attr)


def _compute_aux_width(total_cols: int, aux_visible: bool) -> int:
    if not aux_visible:
        return 0
    width = max(30, min(44, int(total_cols * 0.30)))
    if total_cols - width < 52:
        width = max(26, total_cols - 52)
    return max(0, width)


def _compute_request_list_width(*, total_main_width: int, aux_visible: bool) -> int:
    ratio = 0.30 if aux_visible else 0.34
    minimum = 26 if aux_visible else 30
    maximum = 44 if aux_visible else 52
    width = max(minimum, min(maximum, int(total_main_width * ratio)))
    if total_main_width - width < 42:
        width = max(minimum, total_main_width - 42)
    return max(minimum, width)


def _build_request_lines(entry: LoggedExchange, width: int) -> list[str]:
    lines = [
        f"REQUEST #{entry.request_id}",
        entry.request.start_line,
        f"Client: {entry.client_ip}",
        f"Target: {_target_label(entry)}",
        "",
        "Headers:",
    ]
    lines.extend(f"{name}: {value}" for name, value in entry.request.headers)
    lines.append("")
    lines.append("Body:")
    lines.extend(_body_lines(entry.request.body_preview))
    return _wrap_lines(lines, max(12, width))


def _build_response_lines(entry: LoggedExchange, width: int) -> list[str]:
    lines = ["RESPONSE"]
    if entry.response is None:
        lines.append("<pending>")
        return _wrap_lines(lines, max(12, width))
    lines.append(entry.response.start_line)
    lines.append("Headers:")
    lines.extend(f"{name}: {value}" for name, value in entry.response.headers)
    lines.append("")
    lines.append("Body:")
    lines.extend(_body_lines(entry.response.body_preview))
    return _wrap_lines(lines, max(12, width))


def _wrap_lines(lines: list[str], width: int) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(_wrap_line(line, width))
    return wrapped


def _target_label(entry: LoggedExchange) -> str:
    host = entry.target_host or "-"
    if entry.target_port is None:
        return host
    return f"{host}:{entry.target_port}"


def _body_lines(body_preview: str, *, max_lines: int = 20) -> list[str]:
    if not body_preview:
        return ["<empty>"]
    lines = body_preview.splitlines() or [body_preview]
    if len(lines) <= max_lines:
        return lines
    return lines[:max_lines] + ["...[truncated]"]


def _wrap_line(value: str, width: int) -> list[str]:
    text = _safe_text(value)
    if width <= 1:
        return [text[:1]]
    if text == "":
        return [""]
    chunks: list[str] = []
    current = text
    while len(current) > width:
        chunks.append(current[:width])
        current = current[width:]
    chunks.append(current)
    return chunks


def _fit_text(value: str, width: int) -> str:
    text = _safe_text(value)
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:1]
    return text[: width - 1] + "~"


def _ensure_visible(cursor: int, scroll: int, height: int) -> int:
    if height <= 0:
        return 0
    if cursor < scroll:
        return cursor
    if cursor >= scroll + height:
        return cursor - height + 1
    return scroll


def _safe_addnstr(stdscr: "curses._CursesWindow", row: int, col: int, text: str, width: int, attr: int) -> None:
    try:
        stdscr.addnstr(row, col, text, width, attr)
    except curses.error:
        pass


def _safe_addch(stdscr: "curses._CursesWindow", row: int, col: int, value: str) -> None:
    try:
        stdscr.addch(row, col, value)
    except curses.error:
        pass


def _safe_text(value: str) -> str:
    return value.replace("\x00", "\\x00")
