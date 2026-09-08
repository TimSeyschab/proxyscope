import gzip
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from proxyscope.adapters.editing.external_editor import resolve_editor_command as _resolve_editor_command
from proxyscope.adapters.editing.external_editor import run_editor as _run_editor
from proxyscope.application.processing.headers import header_value as _header_value_case_insensitive
from proxyscope.application.processing.headers import remove_header as _remove_header_case_insensitive
from proxyscope.application.response_edits import PendingResponseEdit, ResponseEditorResult


@dataclass(frozen=True)
class _BodyEditPlan:
    is_text: bool
    charset: str
    editor_body: bytes
    remove_content_encoding_header: bool


def edit_pending_response_with_external_editor(
    pending: PendingResponseEdit,
) -> ResponseEditorResult:
    editor = _resolve_editor_command()
    if editor is None:
        pending.keep_original()
        return ResponseEditorResult(False, "No editor found. Set $EDITOR (or install nano/vim/vi).")

    try:
        with tempfile.TemporaryDirectory(prefix="pscope-edit-") as tmp_dir:
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

            print(f"[pscope] Editing response for {pending.request_url}")
            print(f"[pscope] Opened {header_file.name} then {body_file.name} in {editor}")
            if edit_plan.is_text:
                print(f"[pscope] Body edit mode: text (original charset: {edit_plan.charset})")
            else:
                print("[pscope] Body edit mode: binary")

            _run_editor(editor, header_file)
            _run_editor(editor, body_file)

            edited_headers, edited_body = _read_edited_payload(
                header_file=header_file,
                body_file=body_file,
                body_plan=edit_plan,
            )

            pending.apply(headers=edited_headers, body=edited_body)
            return ResponseEditorResult(
                True,
                f"Applied response edits for {pending.request_url}",
                headers=edited_headers,
                body=edited_body,
            )
    except Exception as exc:  # noqa: BLE001
        pending.keep_original()
        return ResponseEditorResult(False, f"Response edit failed ({exc}); kept original response.")


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
