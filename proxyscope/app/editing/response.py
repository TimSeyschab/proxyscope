import gzip
import os
import shlex
import shutil
import subprocess
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.editing.modifier import PendingResponseEdit


@dataclass(frozen=True)
class _BodyEditPlan:
    is_text: bool
    charset: str
    editor_body: bytes
    remove_content_encoding_header: bool


def edit_pending_response_with_external_editor(
    pending: PendingResponseEdit,
    *,
    runtime_config: RuntimeConfig,
) -> tuple[bool, str]:
    editor = _resolve_editor_command()
    if editor is None:
        pending.keep_original()
        return False, "No editor found. Set $EDITOR (or install nano/vim/vi)."

    try:
        with tempfile.TemporaryDirectory(prefix="tproxy-edit-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            header_file = tmp_path / "headers.txt"
            body_file = tmp_path / "body.txt"

            header_lines = [f"{name}: {value}" for name, value in pending.response.headers.items()]
            header_file.write_text("\n".join(header_lines) + "\n", encoding="utf-8")

            edit_plan = _build_body_edit_plan(
                headers=pending.response.headers,
                body=pending.response.body,
            )
            _write_body_file_for_editor(body_file=body_file, body_plan=edit_plan, original_body=pending.response.body)

            print(f"[tproxy] Editing response for {pending.request_url}")
            print(f"[tproxy] Opened {header_file.name} then {body_file.name} in {editor}")
            if edit_plan.is_text:
                print(f"[tproxy] Body edit mode: text (original charset: {edit_plan.charset})")
            else:
                print("[tproxy] Body edit mode: binary")

            _run_editor(editor, header_file)
            _run_editor(editor, body_file)

            edited_headers, edited_body = _read_edited_payload(
                header_file=header_file,
                body_file=body_file,
                body_plan=edit_plan,
            )

            pending.apply(headers=edited_headers, body=edited_body)
            saved_policy_name = _maybe_save_static_response_rule(
                pending=pending,
                headers=edited_headers,
                body=edited_body,
                runtime_config=runtime_config,
            )
            if saved_policy_name is not None:
                return True, f"Applied response edits and saved static policy {saved_policy_name}."
            return True, f"Applied response edits for {pending.request_url}"
    except Exception as exc:  # noqa: BLE001
        pending.keep_original()
        return False, f"Response edit failed ({exc}); kept original response."


def _build_body_edit_plan(*, headers: dict[str, str], body: bytes) -> _BodyEditPlan:
    body_is_text, body_charset = _is_textual_response_body(headers=headers, body=body)
    content_encoding = _header_value_case_insensitive(headers, "Content-Encoding").lower()
    if body_is_text and content_encoding and content_encoding != "identity":
        decoded = _decode_content_encoded_body(body, content_encoding)
        if decoded is not None:
            return _BodyEditPlan(
                is_text=True,
                charset=body_charset,
                editor_body=decoded,
                remove_content_encoding_header=True,
            )
        return _BodyEditPlan(
            is_text=False,
            charset=body_charset,
            editor_body=body,
            remove_content_encoding_header=False,
        )
    return _BodyEditPlan(
        is_text=body_is_text,
        charset=body_charset,
        editor_body=body,
        remove_content_encoding_header=False,
    )


def _write_body_file_for_editor(*, body_file: Path, body_plan: _BodyEditPlan, original_body: bytes) -> None:
    if body_plan.is_text:
        decoded = body_plan.editor_body.decode(body_plan.charset, errors="replace")
        body_file.write_text(decoded, encoding="utf-8")
        return
    body_file.write_bytes(original_body)


def _read_edited_payload(
    *,
    header_file: Path,
    body_file: Path,
    body_plan: _BodyEditPlan,
) -> tuple[dict[str, str], bytes]:
    edited_headers = _parse_header_file(header_file)
    if body_plan.is_text:
        edited_text = body_file.read_text(encoding="utf-8", errors="replace")
        edited_body = edited_text.encode(body_plan.charset, errors="replace")
        if body_plan.remove_content_encoding_header:
            _remove_header_case_insensitive(edited_headers, "Content-Encoding")
        return edited_headers, edited_body
    return edited_headers, body_file.read_bytes()


def _run_editor(editor: str, file_path: Path) -> None:
    cmd = shlex.split(editor) + [str(file_path)]
    subprocess.run(cmd, check=True)


def _parse_header_file(path: Path) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip()] = value.strip()
    return headers


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


def _is_textual_response_body(*, headers: dict[str, str], body: bytes) -> tuple[bool, str]:
    if not body:
        return True, "utf-8"

    content_type = _header_value_case_insensitive(headers, "Content-Type").lower()
    charset = _extract_charset(content_type) or "utf-8"

    textual_markers = (
        "text/",
        "application/json",
        "application/javascript",
        "application/x-javascript",
        "application/xml",
        "application/xhtml+xml",
        "application/x-www-form-urlencoded",
        "image/svg+xml",
    )
    if any(marker in content_type for marker in textual_markers):
        return True, charset

    if b"\x00" not in body:
        try:
            body.decode("utf-8")
            return True, "utf-8"
        except UnicodeDecodeError:
            pass
    return False, charset


def _extract_charset(content_type: str) -> str | None:
    for part in content_type.split(";")[1:]:
        token = part.strip()
        if not token.lower().startswith("charset="):
            continue
        value = token.split("=", 1)[1].strip().strip('"').strip("'")
        return value or None
    return None


def _header_value_case_insensitive(headers: dict[str, str], header_name: str) -> str:
    target = header_name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return ""


def _decode_content_encoded_body(body: bytes, content_encoding: str) -> bytes | None:
    encoding = content_encoding.strip().lower()
    if "," in encoding:
        encoding = encoding.split(",")[-1].strip()

    if encoding in {"", "identity"}:
        return body
    if encoding == "gzip":
        try:
            return gzip.decompress(body)
        except OSError:
            return None
    if encoding == "deflate":
        try:
            return zlib.decompress(body)
        except zlib.error:
            return None
    if encoding == "br":
        try:
            import brotli  # type: ignore[import-not-found]
        except Exception:
            return None
        try:
            return brotli.decompress(body)
        except Exception:
            return None
    return None


def _remove_header_case_insensitive(headers: dict[str, str], header_name: str) -> None:
    target = header_name.lower()
    for key in list(headers.keys()):
        if key.lower() == target:
            del headers[key]


def _maybe_save_static_response_rule(
    *,
    pending: PendingResponseEdit,
    headers: dict[str, str],
    body: bytes,
    runtime_config: RuntimeConfig,
) -> str | None:
    try:
        answer = (
            input(f"[tproxy] Save edited response as static policy for {pending.method} {pending.request_url}? [y/N]: ")
            .strip()
            .lower()
        )
    except EOFError:
        return None
    if answer not in {"y", "yes"}:
        return None

    static_headers = dict(headers)
    _remove_header_case_insensitive(static_headers, "Transfer-Encoding")
    static_headers["Content-Length"] = str(len(body))

    try:
        policy_name = runtime_config.add_static_response_rule(
            url=pending.request_url,
            status_code=pending.response.status_code,
            reason=pending.response.reason,
            headers=static_headers,
            body=body,
            method=pending.method,
            url_prefix=False,
        )
        runtime_config.remove_open_editor_policy(pending.request_url, method=pending.method)
        return policy_name
    except ValueError:
        return None
