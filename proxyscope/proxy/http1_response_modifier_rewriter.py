from collections.abc import Callable

from proxyscope.proxy.forwarding import ForwardResponse
from proxyscope.proxy.runtime import PolicyEvaluator, ResponseTransformer


class HTTP1ResponseModifierRewriter:
    """
    Buffer and parse HTTP/1.x responses from a TLS stream, and allow
    interactive modification before forwarding bytes to the client.
    """

    def __init__(
        self,
        *,
        policy_evaluator: PolicyEvaluator,
        response_modifier: ResponseTransformer,
        acquire_request_meta: Callable[[], tuple[str, str] | None],
    ) -> None:
        self._policy_evaluator = policy_evaluator
        self._response_modifier = response_modifier
        self._acquire_request_meta = acquire_request_meta
        self._buffer = bytearray()
        self._passthrough = False
        self._active_request_meta: tuple[str, str] | None = None

    def feed(self, data: bytes) -> bytes:
        if self._passthrough:
            return data

        self._buffer.extend(data)
        out = bytearray()

        while True:
            header_end = self._buffer.find(b"\r\n\r\n")
            if header_end < 0:
                break

            raw_header_block = bytes(self._buffer[:header_end])
            lines = raw_header_block.decode("iso-8859-1", errors="replace").split("\r\n")
            if not lines:
                self._passthrough = True
                out.extend(self._flush_buffer())
                break

            start_line = lines[0].strip()
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if not line or ":" not in line:
                    continue
                name, value = line.split(":", 1)
                headers[name.strip()] = value.strip()

            if self._active_request_meta is None:
                self._active_request_meta = self._acquire_request_meta()
            request_meta = self._active_request_meta
            method = request_meta[0] if request_meta is not None else "GET"
            request_url = request_meta[1] if request_meta is not None else "https://unknown/"

            consumed = header_end + 4
            transfer_encoding = _header_value(headers, "transfer-encoding").lower()
            content_length_value = _header_value(headers, "content-length")

            raw_body = b""
            decoded_body = b""

            if _response_has_no_body(method, start_line):
                decoded_body = b""
                raw_body = b""
            elif "chunked" in transfer_encoding:
                parsed = _try_consume_chunked(bytes(self._buffer[consumed:]))
                if parsed is None:
                    break
                raw_chunked, decoded = parsed
                raw_body = raw_chunked
                decoded_body = decoded
                consumed += len(raw_chunked)
            elif content_length_value:
                try:
                    content_length = max(0, int(content_length_value))
                except ValueError:
                    self._passthrough = True
                    out.extend(self._flush_buffer())
                    break
                if len(self._buffer) < consumed + content_length:
                    break
                raw_body = bytes(self._buffer[consumed : consumed + content_length])
                decoded_body = raw_body
                consumed += content_length
            else:
                # Unknown body framing (usually close-delimited). Do not rewrite.
                self._passthrough = True
                out.extend(self._flush_buffer())
                break

            del self._buffer[:consumed]

            status_code, reason, version = _parse_response_start_line(start_line)
            if _is_interim_response(status_code):
                out.extend(raw_header_block)
                out.extend(b"\r\n\r\n")
                out.extend(raw_body)
                continue

            original_response = ForwardResponse(
                status_code=status_code,
                reason=reason,
                headers=headers,
                body=decoded_body,
            )
            static_template = self._policy_evaluator.get_static_response_template_for_request(
                method=method, url=request_url
            )
            if static_template is not None:
                final_response = ForwardResponse(
                    status_code=static_template.status_code,
                    reason=static_template.reason,
                    headers=dict(static_template.headers),
                    body=static_template.body,
                )
            else:
                edited_response = self._response_modifier.maybe_modify_response(
                    request_url=request_url,
                    method=method,
                    response=original_response,
                )
                if edited_response is original_response:
                    out.extend(raw_header_block)
                    out.extend(b"\r\n\r\n")
                    out.extend(raw_body)
                    self._active_request_meta = None
                    continue
                final_response = edited_response

            out.extend(_build_response_bytes(version=version, response=final_response))
            self._active_request_meta = None

        return bytes(out)

    def flush(self) -> bytes:
        return self._flush_buffer()

    def _flush_buffer(self) -> bytes:
        if not self._buffer:
            return b""
        payload = bytes(self._buffer)
        self._buffer.clear()
        return payload


def _response_has_no_body(method: str, start_line: str) -> bool:
    code, _reason, _version = _parse_response_start_line(start_line)
    if method.upper() == "HEAD":
        return True
    if 100 <= code < 200:
        return True
    return code in {204, 304}


def _parse_response_start_line(start_line: str) -> tuple[int, str, str]:
    parts = start_line.split(" ", 2)
    version = parts[0] if parts else "HTTP/1.1"
    if len(parts) >= 2:
        try:
            code = int(parts[1])
        except ValueError:
            code = 200
    else:
        code = 200
    reason = parts[2] if len(parts) >= 3 else ""
    return code, reason, version


def _is_interim_response(status_code: int) -> bool:
    return 100 <= status_code < 200 and status_code != 101


def _build_response_bytes(*, version: str, response: ForwardResponse) -> bytes:
    headers = dict(response.headers)
    _remove_header_case_insensitive(headers, "Transfer-Encoding")
    headers["Content-Length"] = str(len(response.body))
    start_line = f"{version} {response.status_code} {response.reason}".rstrip()
    lines = [start_line]
    for name, value in headers.items():
        lines.append(f"{name}: {value}")
    return "\r\n".join(lines).encode("iso-8859-1", errors="replace") + b"\r\n\r\n" + response.body


def _remove_header_case_insensitive(headers: dict[str, str], header_name: str) -> None:
    target = header_name.lower()
    for key in list(headers.keys()):
        if key.lower() == target:
            del headers[key]


def _header_value(headers: dict[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return ""


def _try_consume_chunked(data: bytes) -> tuple[bytes, bytes] | None:
    idx = 0
    decoded = bytearray()
    data_len = len(data)

    while True:
        line_end = data.find(b"\r\n", idx)
        if line_end < 0:
            return None
        line = data[idx:line_end]
        try:
            chunk_size = int(line.split(b";", 1)[0], 16)
        except ValueError:
            return None
        idx = line_end + 2

        if chunk_size == 0:
            trailer_end = data.find(b"\r\n\r\n", idx)
            if trailer_end >= 0:
                idx = trailer_end + 4
                return data[:idx], bytes(decoded)
            if idx + 2 <= data_len and data[idx : idx + 2] == b"\r\n":
                idx += 2
                return data[:idx], bytes(decoded)
            return None

        if idx + chunk_size + 2 > data_len:
            return None
        decoded.extend(data[idx : idx + chunk_size])
        idx = idx + chunk_size
        if data[idx : idx + 2] != b"\r\n":
            return None
        idx += 2
