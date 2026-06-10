from collections import Counter

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.runtime.journal import LoggedExchange
from proxyscope.app.runtime.ui_models import (
    AuxPanelModel,
    AuxPanelTabModel,
    DetailTab,
    RequestDetailModel,
    RequestListModel,
    RequestRowModel,
    RuntimeScreenModel,
    StatusBarModel,
)
from proxyscope.app.runtime.ui_state import RuntimeUIViewState


def build_runtime_screen_model(
    *,
    state: RuntimeUIViewState,
    runtime_config: RuntimeConfig,
    entries: list[LoggedExchange],
    all_entry_count: int,
    site_counter: Counter[str],
    policy_items: list[str],
    filter_summary: str,
) -> RuntimeScreenModel:
    site_items = site_counter.most_common()
    entries_whitelist = runtime_config.whitelist_entries()
    whitelist_text = "*" if not entries_whitelist else ",".join(entries_whitelist[:3])
    if len(entries_whitelist) > 3:
        whitelist_text += ",..."
    cache_text = "on" if runtime_config.cache_invalidation_enabled else "off"
    mitm_text = "on" if runtime_config.mitm_enabled else "off"
    policy_count = len(runtime_config.policy_rules())
    editor_policy_count = len(runtime_config.open_editor_policy_entries())
    config_path = runtime_config.config_path
    config_path_text = "-" if config_path is None else str(config_path)
    config_text = (
        f"level={runtime_config.log_level_name()} "
        f"whitelist={whitelist_text} "
        f"cache_invalidation={cache_text} "
        f"mitm={mitm_text} "
        f"editor_policies={editor_policy_count} "
        f"policies={policy_count} "
        f"filter={filter_summary} "
        f"config={config_path_text}"
    )
    request_title = f"MAIN {len(entries)}/{all_entry_count}"
    selected_entry = entries[state.request_cursor] if entries else None

    return RuntimeScreenModel(
        request_list=RequestListModel(
            title=request_title,
            rows=_build_request_rows(entries),
            selected_request_id=None if selected_entry is None else selected_entry.request_id,
            cursor=state.request_cursor,
        ),
        detail=RequestDetailModel(
            tab=state.detail_tab,
            text=_format_detail(selected_entry, state.detail_tab),
            has_response=selected_entry is not None and selected_entry.response is not None,
        ),
        aux=AuxPanelModel(
            visible=state.aux_visible,
            aux_tabs=_build_aux_tabs(
                site_items=site_items,
                policy_items=policy_items,
                site_cursor=state.site_cursor,
                policy_cursor=state.policy_cursor,
            ),
            active_key=state.aux_tab_key,
        ),
        status_bar=StatusBarModel(
            message=state.status_message,
            config_text=config_text,
        ),
        main_mode=state.main_mode,
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


def _build_aux_tabs(
    *,
    site_items: list[tuple[str, int]],
    policy_items: list[str],
    site_cursor: int,
    policy_cursor: int,
) -> list[AuxPanelTabModel]:
    site_rows = [f"{count:5d}  {host}" for host, count in site_items]
    return [
        AuxPanelTabModel(
            key="sites",
            title="SIDEBAR:SITES",
            items=site_rows,
            cursor=site_cursor,
            empty_label="No sites recorded.",
        ),
        AuxPanelTabModel(
            key="policies",
            title="SIDEBAR:POLICIES",
            items=policy_items,
            cursor=policy_cursor,
            empty_label="No policies configured.",
        ),
    ]
