from collections import Counter

from proxyscope.adapters.tui.models import (
    DetailTab,
    RequestDetailModel,
    RequestListModel,
    RequestRowModel,
    RuntimeScreenModel,
    StatusBarModel,
    TabbedListModel,
    TabbedListTabModel,
)
from proxyscope.adapters.tui.state import RuntimeUIViewState
from proxyscope.application.journal import LoggedExchange
from proxyscope.application.requests import RequestWindow
from proxyscope.application.runtime_view import RuntimeStatusSnapshot


def build_runtime_screen_model(
    *,
    state: RuntimeUIViewState,
    runtime_status: RuntimeStatusSnapshot,
    request_window: RequestWindow,
    site_counter: Counter[str],
    policy_items: list[str],
) -> RuntimeScreenModel:
    site_items = site_counter.most_common()
    entries_whitelist = runtime_status.whitelist_entries
    whitelist_text = "*" if not entries_whitelist else ",".join(entries_whitelist[:3])
    if len(entries_whitelist) > 3:
        whitelist_text += ",..."
    cache_text = "on" if runtime_status.cache_invalidation_enabled else "off"
    mitm_text = "on" if runtime_status.mitm_enabled else "off"
    config_path = runtime_status.config_path
    config_path_text = "-" if config_path is None else str(config_path)
    config_text = (
        f"level={runtime_status.log_level_name} "
        f"whitelist={whitelist_text} "
        f"cache_invalidation={cache_text} "
        f"mitm={mitm_text} "
        f"editor_policies={runtime_status.editor_policy_count} "
        f"policies={runtime_status.policy_count} "
        f"filter={runtime_status.request_filter_summary} "
        f"config={config_path_text}"
    )
    request_title = f"MAIN {request_window.total_count}/{request_window.all_count}"
    selected_entry = request_window.selected_entry

    return RuntimeScreenModel(
        request_list=RequestListModel(
            title=request_title,
            rows=_build_request_rows(request_window.entries),
            selected_request_id=None if selected_entry is None else selected_entry.request_id,
            cursor=state.request_cursor,
            row_offset=request_window.offset,
            follow_top=state.request_follow_top,
        ),
        detail=RequestDetailModel(
            tab=state.detail_tab,
            text=_format_detail(selected_entry, state.detail_tab),
            has_response=selected_entry is not None and selected_entry.response is not None,
        ),
        detail_visible=state.detail_visible,
        detail_ratio=state.detail_ratio,
        admin=TabbedListModel(
            tabs=_build_admin_tabs(
                site_items=site_items,
                policy_items=policy_items,
                site_cursor=state.site_cursor,
                policy_cursor=state.policy_cursor,
            ),
            active_key=state.admin_tab_key,
        ),
        status_bar=StatusBarModel(
            message=state.status_message,
            config_text=config_text,
        ),
        active_view=state.active_view,
        active_pane=state.active_pane,
    )


def _build_request_rows(entries: list[LoggedExchange]) -> list[RequestRowModel]:
    return [_build_request_row(entry) for entry in entries]


def _build_request_row(entry: LoggedExchange) -> RequestRowModel:
    status = "---" if entry.response is None else str(entry.response.status_code)
    host = entry.target_host or "-"
    duration = "-" if entry.duration_ms is None else f"{entry.duration_ms:.1f}ms"
    return RequestRowModel(
        request_id=entry.request_id,
        cells=(
            str(entry.request_id),
            status,
            entry.request.method,
            host,
            entry.request.path,
            duration,
        ),
    )


def _format_detail(entry: LoggedExchange | None, detail_tab: DetailTab) -> str:
    if entry is None:
        return "No request selected."
    if detail_tab == "response":
        return _format_response_detail(entry)
    return _format_request_detail(entry)


def _format_request_detail(entry: LoggedExchange) -> str:
    header_lines = "\n".join(f"{name}: {value}" for name, value in entry.request.headers) or "<none>"
    body = entry.request.body_preview or "<empty>"
    return (
        f"{entry.request.start_line}\n"
        f"host: {entry.target_host or '-'}\n"
        f"port: {entry.target_port if entry.target_port is not None else '-'}\n"
        f"protocol: {entry.protocol}\n"
        f"client: {entry.client_ip}\n\n"
        f"headers\n"
        f"{header_lines}\n\n"
        f"body\n"
        f"{body}"
    )


def _format_response_detail(entry: LoggedExchange) -> str:
    if entry.response is None:
        return "No response captured."
    header_lines = "\n".join(f"{name}: {value}" for name, value in entry.response.headers) or "<none>"
    body = entry.response.body_preview or "<empty>"
    size = "-" if entry.response.body_size is None else str(entry.response.body_size)
    duration = "-" if entry.duration_ms is None else f"{entry.duration_ms:.1f}ms"
    return (
        f"{entry.response.start_line}\n"
        f"status: {entry.response.status_code} {entry.response.reason}\n"
        f"duration: {duration}\n"
        f"size: {size}\n\n"
        f"headers\n"
        f"{header_lines}\n\n"
        f"body\n"
        f"{body}"
    )


def _build_admin_tabs(
    *,
    site_items: list[tuple[str, int]],
    policy_items: list[str],
    site_cursor: int,
    policy_cursor: int,
) -> list[TabbedListTabModel]:
    site_rows = [f"{count:5d}  {host}" for host, count in site_items]
    return [
        TabbedListTabModel(
            key="sites",
            title="Sites",
            items=site_rows,
            cursor=site_cursor,
            empty_label="No sites recorded.",
        ),
        TabbedListTabModel(
            key="policies",
            title="Policies",
            items=policy_items,
            cursor=policy_cursor,
            empty_label="No policies configured.",
        ),
    ]
