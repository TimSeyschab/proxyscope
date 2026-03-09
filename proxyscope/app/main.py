from argparse import ArgumentParser
import logging
import sys
import threading

from proxyscope.app.config.runtime import RuntimeConfig, set_runtime_config
from proxyscope.app.logging.setup import configure_logging
from proxyscope.app.logging.observability import set_runtime_observer
from proxyscope.app.runtime.journal import RequestJournal, set_request_journal
from proxyscope.app.editing.modifier import ResponseModifierService, set_response_modifier
from proxyscope.app.runtime.cli import RuntimeCLI
from proxyscope.proxy.server import ProxyHTTPServer, create_server

LOGGER = logging.getLogger("tproxy.app")


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Minimal HTTP proxy learning server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", default=8080, type=int, help="Port to bind")
    parser.add_argument("--config", default=None, help="Path to JSON runtime configuration file")
    parser.add_argument("--no-ui", action="store_true", help="Disable interactive runtime CLI UI")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    runtime_config = RuntimeConfig.load_from_file(args.config) if args.config else RuntimeConfig()
    request_journal = RequestJournal()
    response_modifier = ResponseModifierService()
    set_runtime_config(runtime_config)
    set_request_journal(request_journal)
    set_response_modifier(response_modifier)
    configure_logging(level=runtime_config.log_level)

    server = create_server(args.host, args.port)
    LOGGER.info("Listening on http://%s:%d", args.host, args.port)

    use_ui = not args.no_ui and sys.stdin.isatty() and sys.stdout.isatty()

    if not use_ui:
        response_modifier.set_interactive_enabled(False)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            LOGGER.info("Shutdown requested")
        finally:
            server.server_close()
        return

    response_modifier.set_interactive_enabled(True)
    runtime_ui = RuntimeCLI(
        runtime_config=runtime_config,
        request_journal=request_journal,
        response_modifier=response_modifier,
        proxy_base_url=f"http://{args.host}:{args.port}",
    )
    runtime_ui.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%H:%M:%S")
    )

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    root_logger.addHandler(runtime_ui)
    root_logger.setLevel(runtime_config.log_level)
    set_runtime_observer(runtime_ui)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    def close_active_ssl_tunnels() -> None:
        if not isinstance(server, ProxyHTTPServer):
            return
        closed = server.close_all_active_tunnels()
        LOGGER.info("Closed %d active SSL tunnel(s) after cache setting change.", closed)

    try:
        runtime_ui.run(shutdown_server=server.shutdown, on_cache_toggle=close_active_ssl_tunnels)
    except KeyboardInterrupt:
        LOGGER.info("Shutdown requested")
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        set_runtime_observer(None)


if __name__ == "__main__":
    main()
