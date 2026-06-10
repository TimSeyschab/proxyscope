import base64
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TypedDict

import requests

from proxyscope.application.journal import LoggedExchange


class ReplayPayload(TypedDict):
    method: str
    url: str
    headers: dict[str, str]
    body: bytes


def edit_and_resend_logged_request(
    entry: LoggedExchange,
    *,
    request_url: str,
    proxy_base_url: str | None,
) -> tuple[bool, str]:
    editor = _resolve_editor_command()
    if editor is None:
        return False, "No editor found. Set $EDITOR (or install nano/vim/vi)."

    payload = _build_edit_payload(entry, request_url=request_url)
    try:
        with tempfile.TemporaryDirectory(prefix="pscope-replay-") as tmp_dir:
            file_path = Path(tmp_dir) / "request.json"
            file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

            print(f"[pscope] Editing request replay payload in {file_path.name} ({editor})")
            _run_editor(editor, file_path)

            edited_payload = json.loads(file_path.read_text(encoding="utf-8"))
            replay = _parse_replay_payload(edited_payload)
            replay_headers = _sanitize_replay_headers(replay["headers"])

            proxies = None
            if proxy_base_url:
                proxies = {"http": proxy_base_url, "https": proxy_base_url}
            verify_tls = False if proxy_base_url else True

            response = requests.request(
                replay["method"],
                replay["url"],
                headers=replay_headers,
                data=replay["body"],
                timeout=60,
                allow_redirects=False,
                proxies=proxies,
                verify=verify_tls,
            )
            return True, f"Replayed {replay['method']} {replay['url']} -> {response.status_code} {response.reason}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Replay failed ({exc})."


def _build_edit_payload(entry: LoggedExchange, *, request_url: str) -> dict[str, object]:
    headers = {name: value for name, value in entry.request.headers}
    payload: dict[str, object] = {
        "method": entry.request.method,
        "url": request_url,
        "headers": headers,
    }
    body = entry.request.body
    if body is None:
        payload["body_text"] = ""
        return payload
    try:
        payload["body_text"] = body.decode("utf-8")
    except UnicodeDecodeError:
        payload["body_base64"] = base64.b64encode(body).decode("ascii")
        payload["body_encoding"] = "base64"
    return payload


def _parse_replay_payload(payload: object) -> ReplayPayload:
    if not isinstance(payload, dict):
        raise ValueError("Replay payload must be a JSON object.")

    method_raw = payload.get("method", "GET")
    method = str(method_raw).strip().upper()
    if not method:
        raise ValueError("method must not be empty.")

    url_raw = payload.get("url", "")
    url = str(url_raw).strip()
    if not url:
        raise ValueError("url must not be empty.")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("url must start with http:// or https://")

    headers_raw = payload.get("headers", {})
    headers = dict(headers_raw) if isinstance(headers_raw, dict) else {}
    normalized_headers = {str(k): str(v) for k, v in headers.items()}

    body_text_raw = payload.get("body_text")
    body_base64_raw = payload.get("body_base64")
    if body_base64_raw not in (None, ""):
        try:
            body_bytes = base64.b64decode(str(body_base64_raw), validate=True)
        except ValueError as exc:
            raise ValueError("body_base64 must be valid base64.") from exc
    elif body_text_raw is None:
        body_bytes = b""
    else:
        body_bytes = str(body_text_raw).encode("utf-8")

    return {
        "method": method,
        "url": url,
        "headers": normalized_headers,
        "body": body_bytes,
    }


def _sanitize_replay_headers(headers: dict[str, str]) -> dict[str, str]:
    sanitized = dict(headers)
    for name in (
        "Host",
        "Content-Length",
        "Connection",
        "Proxy-Connection",
        "Transfer-Encoding",
    ):
        _remove_header_case_insensitive(sanitized, name)
    return sanitized


def _remove_header_case_insensitive(headers: dict[str, str], header_name: str) -> None:
    target = header_name.lower()
    for key in list(headers.keys()):
        if key.lower() == target:
            del headers[key]


def _resolve_editor_command() -> str | None:
    env_editor = os.environ.get("EDITOR")
    if env_editor:
        parts = shlex.split(env_editor)
        if parts and shutil.which(parts[0]) is not None:
            return env_editor

    for candidate in ("nano", "vim", "vi"):
        if shutil.which(candidate) is not None:
            return candidate
    return None


def _run_editor(editor: str, file_path: Path) -> None:
    cmd = shlex.split(editor) + [str(file_path)]
    subprocess.run(cmd, check=True)
