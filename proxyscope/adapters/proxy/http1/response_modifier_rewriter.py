from collections.abc import Callable

from proxyscope.application.processing.headers import header_value as _header_value
from proxyscope.application.processing.headers import remove_header as _remove_header_case_insensitive
from proxyscope.application.processing.models import ExchangeResponse


class HTTP1ResponseModifierRewriter:
    """
    Buffer and parse HTTP/1.x responses from a TLS stream, and allow
    interactive modification before forwarding bytes to the client.
    """

    def __init__(
        self,
        *,
        process_response: Callable[[ExchangeResponse], ExchangeResponse],
        acquire_request_method: Callable[[], str | None],
    ) -> None:
        self._process_response = process_response
        self._acquire_request_method = acquire_request_method
        self._buffer = bytearray()
        self._passthrough = False
        self._active_request_method: str | None = None
        self._close_delimited_response: tuple[str, int, str, dict[str, str], int] | None = None

    def feed(self, data: bytes) -> bytes:
        if self._passthrough:
            return data

        self._buffer.extend(data)
        if self._close_delimited_response is not None:
            return b""
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

            if self._active_request_method is None:
                self._active_request_method = self._acquire_request_method()
            method = self._active_request_method or "GET"
            status_code, reason, version = _parse_response_start_line(start_line)

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
                self._close_delimited_response = (version, status_code, reason, headers, consumed)
                break

            del self._buffer[:consumed]

            if _is_interim_response(status_code):
                out.extend(raw_header_block)
                out.extend(b"\r\n\r\n")
                out.extend(raw_body)
                continue

            original_response = ExchangeResponse(
                status_code=status_code,
                reason=reason,
                headers=headers,
                body=decoded_body,
                body_size=len(decoded_body),
            )
            final_response = self._process_response(original_response)
            if final_response is original_response:
                out.extend(raw_header_block)
                out.extend(b"\r\n\r\n")
                out.extend(raw_body)
                self._active_request_method = None
                continue

            out.extend(_build_response_bytes(version=version, response=final_response))
            self._active_request_method = None

        return bytes(out)

    def flush(self) -> bytes:
        if self._close_delimited_response is not None:
            version, status_code, reason, headers, body_start = self._close_delimited_response
            original_payload = bytes(self._buffer)
            original_response = ExchangeResponse(
                status_code=status_code,
                reason=reason,
                headers=headers,
                body=original_payload[body_start:],
                body_size=len(original_payload) - body_start,
            )
            final_response = self._process_response(original_response)
            self._buffer.clear()
            self._close_delimited_response = None
            self._active_request_method = None
            if final_response is original_response:
                return original_payload
            return _build_response_bytes(version=version, response=final_response)
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


def _build_response_bytes(*, version: str, response: ExchangeResponse) -> bytes:
    headers = dict(response.headers)
    _remove_header_case_insensitive(headers, "Transfer-Encoding")
    headers["Content-Length"] = str(len(response.body))
    start_line = f"{version} {response.status_code} {response.reason}".rstrip()
    lines = [start_line]
    for name, value in headers.items():
        lines.append(f"{name}: {value}")
    return "\r\n".join(lines).encode("iso-8859-1", errors="replace") + b"\r\n\r\n" + response.body




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
