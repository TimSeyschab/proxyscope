class HTTP1RequestHeaderRewriter:
    """
    Stream rewriter for HTTP/1.x requests.
    Rewrites request headers while preserving message framing and body bytes.
    """

    def __init__(self) -> None:
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

                rewritten_headers_block, headers = _rewrite_header_block(raw_header_block)
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


def rewrite_cache_invalidation_headers(headers: dict[str, str]) -> dict[str, str]:
    rewritten: dict[str, str] = {}
    blocked = {
        "if-none-match",
        "if-modified-since",
        "cache-control",
        "pragma",
        "expires",
        "accept-encoding",
    }
    for key, value in headers.items():
        if key.lower() in blocked:
            continue
        rewritten[key] = value

    rewritten["Cache-Control"] = "no-cache, no-store, max-age=0, must-revalidate"
    rewritten["Pragma"] = "no-cache"
    rewritten["Expires"] = "0"
    # Keep upstream payloads uncompressed so TUI preview/editor can work with text bodies.
    rewritten["Accept-Encoding"] = "identity"
    return rewritten


def _rewrite_header_block(raw_header_block: bytes) -> tuple[bytes, dict[str, str]]:
    lines = raw_header_block.decode("iso-8859-1", errors="replace").split("\r\n")
    if not lines:
        return raw_header_block + b"\r\n\r\n", {}

    start_line = lines[0]
    parsed_headers: dict[str, str] = {}
    ordered: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        name_stripped = name.strip()
        value_stripped = value.strip()
        ordered.append((name_stripped, value_stripped))
        parsed_headers[name_stripped] = value_stripped

    rewritten_headers = rewrite_cache_invalidation_headers(dict(ordered))
    rebuilt_lines = [start_line]
    for name, value in rewritten_headers.items():
        rebuilt_lines.append(f"{name}: {value}")
    rebuilt = "\r\n".join(rebuilt_lines).encode("iso-8859-1", errors="replace") + b"\r\n\r\n"
    return rebuilt, rewritten_headers


def _header_value(headers: dict[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return ""
