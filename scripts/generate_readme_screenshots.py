from __future__ import annotations

import asyncio
from pathlib import Path

from proxyscope.app.config.runtime import RuntimeConfig
from proxyscope.app.editing.modifier import ResponseModifierService
from proxyscope.app.runtime.cli import RuntimeCLI
from proxyscope.app.runtime.journal import RequestJournal
from proxyscope.app.runtime.textual_ui import RuntimeTextualApp

SCREENSHOT_DIR = Path("docs/screenshots")
OVERVIEW_SCREENSHOT = SCREENSHOT_DIR / "01-overview.svg"
DETAIL_SCREENSHOT = SCREENSHOT_DIR / "02-request-detail.svg"
POLICIES_SCREENSHOT = SCREENSHOT_DIR / "03-policies.svg"


def _seed_runtime_data(runtime_cli: RuntimeCLI, journal: RequestJournal, config: RuntimeConfig) -> None:
    first_id = journal.start_request(
        method="GET",
        path="/api/users",
        start_line="GET /api/users HTTP/1.1",
        headers={"Host": "api.example.com", "Accept": "application/json"},
        body=None,
        client_ip="127.0.0.1",
        target_host="api.example.com",
        target_port=443,
        protocol="https-mitm",
    )
    journal.complete_request(
        first_id,
        status_code=200,
        reason="OK",
        start_line="HTTP/1.1 200 OK",
        headers={"Content-Type": "application/json"},
        body=b'{"users":[{"id":1,"name":"Ada"}]}',
        duration_ms=18.4,
        body_size=34,
    )

    second_id = journal.start_request(
        method="POST",
        path="/api/login",
        start_line="POST /api/login HTTP/1.1",
        headers={"Host": "api.example.com", "Content-Type": "application/json"},
        body=b'{"email":"tim@example.com"}',
        client_ip="127.0.0.1",
        target_host="api.example.com",
        target_port=443,
        protocol="https-mitm",
    )
    journal.complete_request(
        second_id,
        status_code=401,
        reason="Unauthorized",
        start_line="HTTP/1.1 401 Unauthorized",
        headers={"Content-Type": "application/json"},
        body=b'{"error":"invalid credentials"}',
        duration_ms=24.9,
        body_size=31,
    )

    journal.start_request(
        method="GET",
        path="/health",
        start_line="GET /health HTTP/1.1",
        headers={"Host": "service.internal"},
        body=None,
        client_ip="127.0.0.1",
        target_host="service.internal",
        target_port=8080,
        protocol="http",
    )

    runtime_cli.on_site_visit("api.example.com")
    runtime_cli.on_site_visit("api.example.com")
    runtime_cli.on_site_visit("service.internal")

    config.add_open_editor_policy("https://api.example.com/api/login", method="POST", priority=20)
    config.add_static_response_rule(
        url="https://service.internal/health",
        method="GET",
        status_code=200,
        reason="OK",
        headers={"Content-Type": "application/json"},
        body=b'{"status":"ok","source":"static policy"}',
        name="health-static",
        priority=10,
    )


async def _capture_screenshots() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    config = RuntimeConfig()
    journal = RequestJournal()
    runtime_cli = RuntimeCLI(
        runtime_config=config,
        request_journal=journal,
        response_modifier=ResponseModifierService(),
        proxy_base_url="http://127.0.0.1:8080",
    )
    _seed_runtime_data(runtime_cli, journal, config)
    runtime_cli.set_status_message("Demo session loaded.")

    app = RuntimeTextualApp(runtime_cli)
    async with app.run_test(size=(160, 42)) as pilot:
        await pilot.pause(0.3)
        app.save_screenshot(str(OVERVIEW_SCREENSHOT))

        runtime_cli.select_request(1)
        runtime_cli.open_selected_request_detail()
        runtime_cli.select_detail_tab("response")
        runtime_cli.set_status_message("Detail view for request #2")
        app._refresh_screen()
        await pilot.pause(0.1)
        app.save_screenshot(str(DETAIL_SCREENSHOT))

        runtime_cli.select_aux_tab("policies")
        runtime_cli.set_status_message("Policies sidebar")
        app._refresh_screen()
        await pilot.pause(0.1)
        app.save_screenshot(str(POLICIES_SCREENSHOT))


def main() -> None:
    asyncio.run(_capture_screenshots())


if __name__ == "__main__":
    main()
