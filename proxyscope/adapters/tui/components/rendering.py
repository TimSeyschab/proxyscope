from rich.text import Text

from proxyscope.adapters.tui.models import AuxPanelTabModel, DetailTab


def plain_text(value: str) -> Text:
    return Text(value, no_wrap=False, overflow="fold")


def format_detail_tabs(*, detail_tab: DetailTab, has_response: bool) -> str:
    request_label = "[Request]" if detail_tab == "request" else " Request "
    response_suffix = "" if has_response else " (pending)"
    response_label = f"[Response{response_suffix}]" if detail_tab == "response" else f" Response{response_suffix} "
    return f"{request_label} | {response_label}"


def format_sidebar_tabs(*, aux_tabs: list[AuxPanelTabModel], active_key: str) -> str:
    labels: list[str] = []
    for tab in aux_tabs:
        label = tab.title.split(":", 1)[-1].title()
        labels.append(f"[{label}]" if tab.key == active_key else f" {label} ")
    return " | ".join(labels) if labels else ""
