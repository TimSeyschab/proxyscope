from http.server import BaseHTTPRequestHandler

from proxyscope.proxy.forwarding import ForwardRequest, ForwardResponse


def map_incoming_request(handler: BaseHTTPRequestHandler) -> ForwardRequest:
    """Map http.server request data into the forwarding request model."""
    # `rfile` is a stream; read exactly Content-Length bytes to avoid partial reads
    # or blocking on methods that include a request body (for example POST/PUT).
    content_length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(content_length) if content_length > 0 else b""
    headers = {name: value for name, value in handler.headers.items()}
    return ForwardRequest(
        method=handler.command,
        path=handler.path,
        headers=headers,
        body=body,
    )


def write_forward_response(
    handler: BaseHTTPRequestHandler,
    response: ForwardResponse,
    *,
    send_body: bool,
) -> None:
    """Write forwarding response model data back to the HTTP client."""
    handler.send_response(response.status_code, response.reason)
    for name, value in response.headers.items():
        handler.send_header(name, value)
    handler.end_headers()

    if send_body:
        handler.wfile.write(response.body)
