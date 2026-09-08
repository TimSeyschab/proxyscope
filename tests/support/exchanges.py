from proxyscope.application.journal import LoggedExchange, RequestJournal


def recorded_exchange(
    *,
    host: str | None = "api.test",
    method: str = "GET",
    path: str = "/items",
    status: int | None = 200,
    port: int | None = 80,
    protocol: str = "http",
) -> LoggedExchange:
    journal = RequestJournal()
    request_id = journal.start_request(
        method=method,
        path=path,
        start_line=f"{method} {path} HTTP/1.1",
        headers={"X-Request": "request-marker"},
        body=b"request-payload",
        client_ip="192.0.2.1",
        target_host=host,
        target_port=port,
        protocol=protocol,
    )
    if status is not None:
        journal.complete_request(
            request_id,
            status_code=status,
            reason="response-reason",
            start_line=f"HTTP/1.1 {status} response-reason",
            headers={"X-Response": "response-marker"},
            body=b"response-payload",
            duration_ms=1,
        )
    return journal.list_entries()[0]
