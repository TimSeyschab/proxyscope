import base64
import json
from datetime import UTC, datetime
from pathlib import Path

from proxyscope.application.journal import LoggedExchange, LoggedRequestMessage, LoggedResponseMessage

FORMAT_JSON = "json"
FORMAT_HAR = "har"
UTF8 = "utf-8"
HAR_VERSION = "1.2"
HAR_CREATOR_NAME = "proxyscope"
DEFAULT_HTTP_VERSION = "HTTP/1.1"
DEFAULT_REQUEST_METHOD = "GET"
DEFAULT_PROTOCOL = "http"
DEFAULT_SCHEME_HTTP = "http"
DEFAULT_SCHEME_HTTPS = "https"
DEFAULT_HTTP_PORT = 80
DEFAULT_HTTPS_PORT = 443
DEFAULT_RESPONSE_STATUS = 0
DEFAULT_TIMING_MS = 0.0
HAR_UNKNOWN_HEADER_SIZE = -1
DEFAULT_BINARY_MIME_TYPE = "application/octet-stream"
HAR_BASE64_ENCODING = "base64"
HAR_RESPONSE_PREVIEW_NOTE = "Response body is exported from the in-memory preview and may be truncated."


def export_entries(entries: list[LoggedExchange], *, format_name: str, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)

    normalized_format = format_name.strip().lower()
    if normalized_format == FORMAT_JSON:
        payload = {"entries": [_serialize_exchange(entry) for entry in entries]}
    elif normalized_format == FORMAT_HAR:
        payload = {
            "log": {
                "version": HAR_VERSION,
                "creator": {"name": HAR_CREATOR_NAME},
                "entries": [_serialize_har_entry(entry) for entry in entries],
            }
        }
    else:
        raise ValueError(f"Unsupported export format: {format_name}")

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding=UTF8)
    return path


def load_entries_from_json(source: str | Path) -> list[LoggedExchange]:
    path = Path(source)
    payload = json.loads(path.read_text(encoding=UTF8))
    entries_raw = payload.get("entries")
    if not isinstance(entries_raw, list):
        raise ValueError("Session file must contain an 'entries' array.")
    return [_parse_exchange(item) for item in entries_raw]


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


def _parse_exchange(payload: object) -> LoggedExchange:
    if not isinstance(payload, dict):
        raise ValueError("Each session entry must be an object.")
    request_payload = payload.get("request")
    if not isinstance(request_payload, dict):
        raise ValueError("Session entry is missing a request object.")
    response_payload = payload.get("response")
    request = LoggedRequestMessage(
        method=str(request_payload.get("method", DEFAULT_REQUEST_METHOD)),
        path=str(request_payload.get("path", "")),
        start_line=str(request_payload.get("start_line", "")),
        headers=_parse_headers(request_payload.get("headers")),
        body_preview=str(request_payload.get("body_preview", "")),
        body=_parse_request_body(request_payload),
    )
    response = None
    if isinstance(response_payload, dict):
        status_code = int(response_payload.get("status_code", DEFAULT_RESPONSE_STATUS))
        response = LoggedResponseMessage(
            status_code=status_code,
            reason=str(response_payload.get("reason", "")),
            start_line=str(response_payload.get("start_line", f"{DEFAULT_HTTP_VERSION} {status_code}")),
            headers=_parse_headers(response_payload.get("headers")),
            body_preview=str(response_payload.get("body_preview", "")),
            body_size=_parse_optional_int(response_payload.get("body_size")),
        )
    return LoggedExchange(
        request_id=int(payload.get("request_id", DEFAULT_RESPONSE_STATUS)),
        started_at=_parse_timestamp(payload.get("started_at")),
        finished_at=_parse_optional_timestamp(payload.get("finished_at")),
        duration_ms=_parse_optional_float(payload.get("duration_ms")),
        client_ip=str(payload.get("client_ip", "")),
        target_host=_parse_optional_str(payload.get("target_host")),
        target_port=_parse_optional_int(payload.get("target_port")),
        protocol=str(payload.get("protocol", DEFAULT_PROTOCOL)),
        request=request,
        response=response,
    )


def _serialize_har_entry(entry: LoggedExchange) -> dict[str, object]:
    request_body = _serialize_request_body(entry.request.body)
    post_data = _build_har_post_data(entry=entry, request_body=request_body)
    response_section = _build_har_response_section(entry)

    return {
        "startedDateTime": _iso8601(entry.started_at),
        "time": entry.duration_ms or DEFAULT_TIMING_MS,
        "request": {
            "method": entry.request.method,
            "url": _entry_url(entry),
            "httpVersion": _http_version_from_start_line(entry.request.start_line),
            "headers": [{"name": name, "value": value} for name, value in entry.request.headers],
            "queryString": [],
            "headersSize": HAR_UNKNOWN_HEADER_SIZE,
            "bodySize": len(entry.request.body or b""),
            **({"postData": post_data} if post_data is not None else {}),
        },
        "response": response_section,
        "cache": {},
        "timings": {
            "send": DEFAULT_TIMING_MS,
            "wait": entry.duration_ms or DEFAULT_TIMING_MS,
            "receive": DEFAULT_TIMING_MS,
        },
    }


def _serialize_request_body(body: bytes | None) -> dict[str, object]:
    if body is None:
        return {}
    if body == b"":
        return {"body_text": ""}
    try:
        return {"body_text": body.decode(UTF8)}
    except UnicodeDecodeError:
        return {"body_base64": base64.b64encode(body).decode("ascii")}


def _parse_request_body(payload: dict[str, object]) -> bytes | None:
    body_base64 = payload.get("body_base64")
    if isinstance(body_base64, str):
        return base64.b64decode(body_base64.encode("ascii"))
    body_text = payload.get("body_text")
    if isinstance(body_text, str):
        return body_text.encode(UTF8)
    return None


def _entry_url(entry: LoggedExchange) -> str:
    host = entry.target_host or "-"
    path = entry.request.path
    if path.startswith("http://") or path.startswith("https://"):
        return path
    normalized_path = path if path.startswith("/") else f"/{path}"
    scheme = DEFAULT_SCHEME_HTTPS if entry.protocol.startswith(DEFAULT_SCHEME_HTTPS) else DEFAULT_SCHEME_HTTP
    if entry.target_port is None:
        return f"{scheme}://{host}{normalized_path}"
    default_port = DEFAULT_HTTPS_PORT if scheme == DEFAULT_SCHEME_HTTPS else DEFAULT_HTTP_PORT
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
    return DEFAULT_HTTP_VERSION


def _iso8601(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace("+00:00", "Z")


def _parse_headers(payload: object) -> tuple[tuple[str, str], ...]:
    if isinstance(payload, dict):
        return tuple((str(name), str(value)) for name, value in payload.items())
    return ()


def _parse_timestamp(payload: object) -> float:
    if not isinstance(payload, str):
        return DEFAULT_TIMING_MS
    return datetime.fromisoformat(payload.replace("Z", "+00:00")).timestamp()


def _parse_optional_timestamp(payload: object) -> float | None:
    if payload is None:
        return None
    return _parse_timestamp(payload)


def _parse_optional_int(payload: object) -> int | None:
    if payload is None:
        return None
    if not isinstance(payload, (int, float, str)):
        raise ValueError("Expected an integer value.")
    return int(payload)


def _parse_optional_float(payload: object) -> float | None:
    if payload is None:
        return None
    if not isinstance(payload, (int, float, str)):
        raise ValueError("Expected a numeric value.")
    return float(payload)


def _parse_optional_str(payload: object) -> str | None:
    if payload is None:
        return None
    return str(payload)


def _build_har_post_data(entry: LoggedExchange, request_body: dict[str, object]) -> dict[str, object] | None:
    if not request_body:
        return None
    post_data: dict[str, object] = {
        "mimeType": _header_value(entry.request.headers, "Content-Type") or DEFAULT_BINARY_MIME_TYPE,
    }
    if "body_text" in request_body:
        post_data["text"] = request_body["body_text"]
    if "body_base64" in request_body:
        post_data["text"] = request_body["body_base64"]
        post_data["encoding"] = HAR_BASE64_ENCODING
    return post_data


def _build_har_response_section(entry: LoggedExchange) -> dict[str, object]:
    if entry.response is None:
        return {
            "status": DEFAULT_RESPONSE_STATUS,
            "statusText": "",
            "httpVersion": "",
            "headers": [],
            "content": {
                "size": DEFAULT_RESPONSE_STATUS,
                "mimeType": DEFAULT_BINARY_MIME_TYPE,
                "text": "",
                "comment": HAR_RESPONSE_PREVIEW_NOTE,
            },
            "redirectURL": "",
            "headersSize": HAR_UNKNOWN_HEADER_SIZE,
            "bodySize": DEFAULT_RESPONSE_STATUS,
        }
    response_headers = [{"name": name, "value": value} for name, value in entry.response.headers]
    response_size = entry.response.body_size or DEFAULT_RESPONSE_STATUS
    response_mime_type = _header_value(entry.response.headers, "Content-Type") or DEFAULT_BINARY_MIME_TYPE
    return {
        "status": entry.response.status_code,
        "statusText": entry.response.reason,
        "httpVersion": _http_version_from_start_line(entry.response.start_line),
        "headers": response_headers,
        "content": {
            "size": response_size,
            "mimeType": response_mime_type,
            "text": entry.response.body_preview,
            "comment": HAR_RESPONSE_PREVIEW_NOTE,
        },
        "redirectURL": "",
        "headersSize": HAR_UNKNOWN_HEADER_SIZE,
        "bodySize": response_size,
    }
