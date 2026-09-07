from collections.abc import Mapping, MutableMapping


def header_value(headers: Mapping[str, str], name: str) -> str:
    target = name.lower()
    return next((value for key, value in headers.items() if key.lower() == target), "")


def remove_header(headers: MutableMapping[str, str], name: str) -> None:
    target = name.lower()
    for key in list(headers):
        if key.lower() == target:
            del headers[key]


def headers_for_body(headers: Mapping[str, str], body: bytes) -> dict[str, str]:
    """Return headers with unambiguous framing for a complete buffered body."""
    updated = dict(headers)
    remove_header(updated, "Transfer-Encoding")
    remove_header(updated, "Content-Length")
    updated["Content-Length"] = str(len(body))
    return updated
