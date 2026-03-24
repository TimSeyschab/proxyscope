from collections import Counter

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.runtime.journal import LoggedExchange
from proxyscope.app.runtime.ui_models import AuxPanelTabModel, RuntimeScreenModel
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

    return RuntimeScreenModel(
        request_title=request_title,
        request_entries=entries,
        request_cursor=state.request_cursor,
        main_mode=state.main_mode,
        active_pane=state.active_pane,
        detail_tab=state.detail_tab,
        aux_visible=state.aux_visible,
        aux_tabs=_build_aux_tabs(
            site_items=site_items,
            policy_items=policy_items,
            site_cursor=state.site_cursor,
            policy_cursor=state.policy_cursor,
        ),
        aux_active_key=state.aux_tab_key,
        status_message=state.status_message,
        config_text=config_text,
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
