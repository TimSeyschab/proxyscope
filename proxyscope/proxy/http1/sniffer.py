from collections.abc import Callable


class HTTP1MessageSniffer:
    """
    Incrementally parse HTTP/1.x messages and emit start-line + headers + body.
    Body capture is capped to avoid unbounded memory growth.
    """

    def __init__(
        self,
        on_message: Callable[[str, dict[str, str], bytes], None],
        *,
        max_body_capture_bytes: int = 8192,
    ) -> None:
        self._on_message = on_message
        self._max_body_capture_bytes = max_body_capture_bytes
        self._buffer = bytearray()
        self._mode = "headers"
        self._body_remaining = 0
        self._current_start_line = ""
        self._current_headers: dict[str, str] = {}
        self._current_body = bytearray()

    def feed(self, data: bytes) -> None:
        self._buffer.extend(data)
        while True:
            if self._mode == "headers":
                header_end = self._find_header_end()
                if header_end < 0:
                    return

                start_line, headers = self._consume_headers(header_end)
                if not start_line:
                    continue

                self._current_start_line = start_line
                self._current_headers = headers
                self._current_body.clear()

                transfer_encoding = _header_value(headers, "transfer-encoding").lower()
                if "chunked" in transfer_encoding:
                    self._mode = "chunked"
                    continue

                content_length_value = _header_value(headers, "content-length")
                if content_length_value:
                    try:
                        self._body_remaining = max(0, int(content_length_value))
                    except ValueError:
                        self._body_remaining = 0
                else:
                    self._body_remaining = 0

                if self._body_remaining > 0:
                    self._mode = "content-length"
                    continue

                self._emit_current_message()
                self._mode = "headers"
                continue

            if self._mode == "content-length":
                consumed = self._consume_content_length_body()
                if not consumed:
                    return
                self._emit_current_message()
                self._mode = "headers"
                continue

            if self._mode == "chunked":
                if not self._consume_chunked_body():
                    return
                self._emit_current_message()
                self._mode = "headers"
                continue

            return

    def _emit_current_message(self) -> None:
        self._on_message(self._current_start_line, self._current_headers, bytes(self._current_body))

    def _find_header_end(self) -> int:
        return self._buffer.find(b"\r\n\r\n")

    def _consume_headers(self, header_end: int) -> tuple[str, dict[str, str]]:
        raw_header_block = bytes(self._buffer[:header_end])
        del self._buffer[: header_end + 4]

        lines = raw_header_block.decode("iso-8859-1", errors="replace").split("\r\n")
        if not lines:
            return "", {}

        start_line = lines[0].strip()
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            name, value = line.split(":", 1)
            headers[name.strip()] = value.strip()
        return start_line, headers

    def _consume_content_length_body(self) -> bool:
        if len(self._buffer) < self._body_remaining:
            return False

        if self._body_remaining > 0 and len(self._current_body) < self._max_body_capture_bytes:
            to_copy = min(self._body_remaining, self._max_body_capture_bytes - len(self._current_body))
            self._current_body.extend(self._buffer[:to_copy])

        del self._buffer[: self._body_remaining]
        self._body_remaining = 0
        return True

    def _consume_chunked_body(self) -> bool:
        while True:
            line_end = self._buffer.find(b"\r\n")
            if line_end < 0:
                return False

            chunk_size_line = bytes(self._buffer[:line_end])
            try:
                chunk_size = int(chunk_size_line.split(b";", 1)[0], 16)
            except ValueError:
                self._buffer.clear()
                return False

            if chunk_size == 0:
                size_line_total = line_end + 2
                if len(self._buffer) < size_line_total:
                    return False
                del self._buffer[:size_line_total]

                if self._buffer.startswith(b"\r\n"):
                    del self._buffer[:2]
                    while self._buffer.startswith(b"\r\n"):
                        del self._buffer[:2]
                    return True

                trailer_end = self._buffer.find(b"\r\n\r\n")
                if trailer_end < 0:
                    return False
                del self._buffer[: trailer_end + 4]
                return True

            total_needed = line_end + 2 + chunk_size + 2
            if len(self._buffer) < total_needed:
                return False

            chunk_start = line_end + 2
            if chunk_size > 0 and len(self._current_body) < self._max_body_capture_bytes:
                remaining = self._max_body_capture_bytes - len(self._current_body)
                self._current_body.extend(self._buffer[chunk_start : chunk_start + min(chunk_size, remaining)])

            del self._buffer[:total_needed]


def _header_value(headers: dict[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return ""
