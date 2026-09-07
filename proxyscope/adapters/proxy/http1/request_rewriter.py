from collections.abc import Callable

from proxyscope.application.processing.headers import header_value as _header_value
from proxyscope.application.processing.middleware import rewrite_cache_invalidation_headers


class HTTP1RequestHeaderRewriter:
    """
    Stream rewriter for HTTP/1.x requests.
    Rewrites request headers while preserving message framing and body bytes.
    """

    def __init__(
        self,
        rewrite_headers: Callable[[dict[str, str]], dict[str, str]] = rewrite_cache_invalidation_headers,
    ) -> None:
        self._rewrite_headers = rewrite_headers
        self._buffer = bytearray()
        self._mode = "headers"
        self._body_remaining = 0

    def feed(self, data: bytes) -> bytes:
        self._buffer.extend(data)
        out = bytearray()

        while True:
            if self._mode == "headers":
                header_end = self._buffer.find(b"\r\n\r\n")
                if header_end < 0:
                    break

                raw_header_block = bytes(self._buffer[:header_end])
                del self._buffer[: header_end + 4]

                rewritten_headers_block, headers = _rewrite_header_block(raw_header_block, self._rewrite_headers)
                out.extend(rewritten_headers_block)

                transfer_encoding = _header_value(headers, "transfer-encoding").lower()
                if "chunked" in transfer_encoding:
                    self._mode = "chunked"
                    continue

                content_length = _header_value(headers, "content-length")
                if content_length:
                    try:
                        self._body_remaining = max(0, int(content_length))
                    except ValueError:
                        self._body_remaining = 0
                else:
                    self._body_remaining = 0

                if self._body_remaining > 0:
                    self._mode = "content-length"
                    continue

                self._mode = "headers"
                continue

            if self._mode == "content-length":
                if not self._buffer:
                    break
                to_copy = min(len(self._buffer), self._body_remaining)
                out.extend(self._buffer[:to_copy])
                del self._buffer[:to_copy]
                self._body_remaining -= to_copy
                if self._body_remaining <= 0:
                    self._mode = "headers"
                continue

            if self._mode == "chunked":
                progressed = self._consume_chunked(out)
                if not progressed:
                    break
                continue

            break

        return bytes(out)

    def flush(self) -> bytes:
        """
        Flush buffered bytes (for abrupt stream termination cases).
        """
        if not self._buffer:
            return b""
        data = bytes(self._buffer)
        self._buffer.clear()
        return data

    def _consume_chunked(self, out: bytearray) -> bool:
        line_end = self._buffer.find(b"\r\n")
        if line_end < 0:
            return False

        chunk_size_line = bytes(self._buffer[:line_end])
        try:
            chunk_size = int(chunk_size_line.split(b";", 1)[0], 16)
        except ValueError:
            # Malformed chunked stream, pass through what is buffered and reset.
            out.extend(self._buffer)
            self._buffer.clear()
            self._mode = "headers"
            return True

        if chunk_size == 0:
            trailer_end = self._buffer.find(b"\r\n\r\n", line_end + 2)
            if trailer_end < 0:
                return False
            segment_end = trailer_end + 4
            out.extend(self._buffer[:segment_end])
            del self._buffer[:segment_end]
            self._mode = "headers"
            return True

        total_needed = line_end + 2 + chunk_size + 2
        if len(self._buffer) < total_needed:
            return False

        out.extend(self._buffer[:total_needed])
        del self._buffer[:total_needed]
        return True


def _rewrite_header_block(
    raw_header_block: bytes,
    rewrite_headers: Callable[[dict[str, str]], dict[str, str]],
) -> tuple[bytes, dict[str, str]]:
    lines = raw_header_block.decode("iso-8859-1", errors="replace").split("\r\n")

    start_line = lines[0]
    ordered: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        name_stripped = name.strip()
        value_stripped = value.strip()
        ordered.append((name_stripped, value_stripped))

    rewritten_headers = rewrite_headers(dict(ordered))
    rebuilt_lines = [start_line]
    for name, value in rewritten_headers.items():
        rebuilt_lines.append(f"{name}: {value}")
    rebuilt = "\r\n".join(rebuilt_lines).encode("iso-8859-1", errors="replace") + b"\r\n\r\n"
    return rebuilt, rewritten_headers

