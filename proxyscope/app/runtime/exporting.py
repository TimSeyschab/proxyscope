import base64
from datetime import UTC, datetime
import json
from pathlib import Path

from proxyscope.app.runtime.journal import LoggedExchange


def export_entries(entries: list[LoggedExchange], *, format_name: str, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)

    normalized_format = format_name.strip().lower()
    if normalized_format == "json":
        payload = {"entries": [_serialize_exchange(entry) for entry in entries]}
    elif normalized_format == "har":
        payload = {
            "log": {
                "version": "1.2",
                "creator": {"name": "proxyscope"},
                "entries": [_serialize_har_entry(entry) for entry in entries],
            }
        }
    else:
        raise ValueError(f"Unsupported export format: {format_name}")

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def _serialize_exchange(entry: LoggedExchange) -> dict[str, object]:
    request_body = _serialize_request_body(entry.request.body)
    response_payload = None
    if entry.response is not None:
        response_payload = {
            "status_code": entry.response.status_code,
            "reason": entry.response.reason,
            "headers": dict(entry.response.headers),
            "body_preview": entry.response.body_preview,
            "body_size": entry.response.body_size,
        }

    return {
        "request_id": entry.request_id,
        "started_at": _iso8601(entry.started_at),
        "finished_at": _iso8601(entry.finished_at),
        "duration_ms": entry.duration_ms,
        "client_ip": entry.client_ip,
        "target_host": entry.target_host,
        "target_port": entry.target_port,
        "protocol": entry.protocol,
        "request": {
            "method": entry.request.method,
            "path": entry.request.path,
            "start_line": entry.request.start_line,
            "headers": dict(entry.request.headers),
            "body_preview": entry.request.body_preview,
            **request_body,
        },
        "response": response_payload,
    }


def _serialize_har_entry(entry: LoggedExchange) -> dict[str, object]:
    request_url = _entry_url(entry)
    request_body = _serialize_request_body(entry.request.body)
    request_headers = [{"name": name, "value": value} for name, value in entry.request.headers]

    response_headers: list[dict[str, str]] = []
    response_status = 0
    response_reason = ""
    response_mime_type = "application/octet-stream"
    response_preview = ""
    response_size = 0
    if entry.response is not None:
        response_headers = [{"name": name, "value": value} for name, value in entry.response.headers]
        response_status = entry.response.status_code
        response_reason = entry.response.reason
        response_preview = entry.response.body_preview
        response_size = entry.response.body_size or 0
        response_mime_type = _header_value(entry.response.headers, "Content-Type") or response_mime_type

    post_data: dict[str, object] | None = None
    if request_body:
        post_data = {
            "mimeType": _header_value(entry.request.headers, "Content-Type") or "application/octet-stream",
        }
        if "body_text" in request_body:
            post_data["text"] = request_body["body_text"]
        if "body_base64" in request_body:
            post_data["text"] = request_body["body_base64"]
            post_data["encoding"] = "base64"

    return {
        "startedDateTime": _iso8601(entry.started_at),
        "time": entry.duration_ms or 0.0,
        "request": {
            "method": entry.request.method,
            "url": request_url,
            "httpVersion": _http_version_from_start_line(entry.request.start_line),
            "headers": request_headers,
            "queryString": [],
            "headersSize": -1,
            "bodySize": len(entry.request.body or b""),
            **({"postData": post_data} if post_data is not None else {}),
        },
        "response": {
            "status": response_status,
            "statusText": response_reason,
            "httpVersion": _http_version_from_start_line(entry.response.start_line) if entry.response is not None else "",
            "headers": response_headers,
            "content": {
                "size": response_size,
                "mimeType": response_mime_type,
                "text": response_preview,
                "comment": "Response body is exported from the in-memory preview and may be truncated.",
            },
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": response_size,
        },
        "cache": {},
        "timings": {"send": 0, "wait": entry.duration_ms or 0.0, "receive": 0},
    }


def _serialize_request_body(body: bytes | None) -> dict[str, object]:
    if body is None:
        return {}
    if body == b"":
        return {"body_text": ""}
    try:
        return {"body_text": body.decode("utf-8")}
    except UnicodeDecodeError:
        return {"body_base64": base64.b64encode(body).decode("ascii")}


def _entry_url(entry: LoggedExchange) -> str:
    host = entry.target_host or "-"
    path = entry.request.path
    if path.startswith("http://") or path.startswith("https://"):
        return path
    normalized_path = path if path.startswith("/") else f"/{path}"
    scheme = "https" if entry.protocol.startswith("https") else "http"
    if entry.target_port is None:
        return f"{scheme}://{host}{normalized_path}"
    default_port = 443 if scheme == "https" else 80
    if entry.target_port == default_port:
        return f"{scheme}://{host}{normalized_path}"
    return f"{scheme}://{host}:{entry.target_port}{normalized_path}"


def _header_value(headers: tuple[tuple[str, str], ...], name: str) -> str | None:
    target = name.lower()
    for header_name, value in headers:
        if header_name.lower() == target:
            return value
    return None


def _http_version_from_start_line(start_line: str) -> str:
    parts = start_line.split()
    if parts and parts[-1].startswith("HTTP/"):
        return parts[-1]
    if parts and parts[0].startswith("HTTP/"):
        return parts[0]
    return "HTTP/1.1"


def _iso8601(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace("+00:00", "Z")
