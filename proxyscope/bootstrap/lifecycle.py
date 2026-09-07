import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from proxyscope.adapters.observability.logging import configure_logging
from proxyscope.adapters.proxy.server import ProxyHTTPServer, create_server
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.bootstrap.composition import RuntimeObjectGraph, create_runtime_object_graph

LOGGER = logging.getLogger("pscope.app")


@dataclass(frozen=True)
class ApplicationOptions:
    host: str = "127.0.0.1"
    port: int = 8080
    config_path: str | Path | None = None
    mitm_enabled: bool | None = None
    certs_dir: str | Path | None = None
    edit_timeout_s: float = 60.0
    thread_join_timeout_s: float = 5.0


class ProxyApplication:
    def __init__(
        self,
        options: ApplicationOptions,
        *,
        server_factory: Callable[..., ProxyHTTPServer] = create_server,
    ) -> None:
        self.options = options
        self._server_factory = server_factory
        self._runtime_graph: RuntimeObjectGraph | None = None
        self._server_thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._server_shutdown_lock = threading.Lock()
        self._server_shutdown_requested = False
        self._entered = False
        self._shutdown_complete = False
        self._previous_root_handlers: list[logging.Handler] = []
        self._previous_root_level = logging.NOTSET
        self._logging_configured = False

    @property
    def server(self) -> ProxyHTTPServer:
        if self._runtime_graph is None:
            raise RuntimeError("Application has not been entered.")
        return self._runtime_graph.server

    @property
    def response_modifier(self) -> ResponseModifierService:
        if self._runtime_graph is None:
            raise RuntimeError("Application has not been entered.")
        return self._runtime_graph.response_modifier

    @property
    def runtime_graph(self) -> RuntimeObjectGraph:
        if self._runtime_graph is None:
            raise RuntimeError("Application has not been entered.")
        return self._runtime_graph

    @property
    def server_thread(self) -> threading.Thread:
        if self._server_thread is None:
            raise RuntimeError("Application has not been entered.")
        return self._server_thread

    def __enter__(self) -> "ProxyApplication":
        if self._entered:
            raise RuntimeError("Application lifecycle cannot be entered twice.")
        self._entered = True
        try:
            self._compose()
            self._configure_logging()
            self.response_modifier.set_interactive_enabled(False)
            self.server_thread.start()
            LOGGER.info("Listening on http://%s:%d", *self.server.server_address)
        except Exception:
            self.shutdown()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.shutdown()

    def run(self) -> None:
        if not self._entered:
            raise RuntimeError("Application must be entered before run().")
        try:
            tui = self.runtime_graph.tui
            if tui is None:
                self._wait_for_shutdown()
            else:
                tui.run()
        except KeyboardInterrupt:
            LOGGER.info("Shutdown requested")
        finally:
            self.shutdown()

    def request_shutdown(self) -> None:
        self._shutdown_event.set()
        self._stop_accepting_requests()

    def shutdown(self) -> None:
        with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._shutdown_complete = True

        self._shutdown_event.set()
        server = None if self._runtime_graph is None else self._runtime_graph.server
        thread = self._server_thread
        self._stop_accepting_requests()
        if server is not None:
            server.close_all_active_tunnels()
        if self._runtime_graph is not None:
            self._runtime_graph.response_modifier.set_interactive_enabled(False)
            self._runtime_graph.response_modifier.cancel_pending_edits()
        if server is not None:
            server.server_close()
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=self.options.thread_join_timeout_s)
        if self._runtime_graph is not None:
            self._runtime_graph.runtime_events.set_observer(None)
            self._runtime_graph.event_bus.shutdown()
            self._runtime_graph.event_store.close()
        self._restore_logging()

    def close_active_tunnels(self) -> None:
        closed = self.server.close_all_active_tunnels()
        LOGGER.info("Closed %d active SSL tunnel(s) after cache setting change.", closed)

    def _compose(self) -> None:
        self._runtime_graph = create_runtime_object_graph(
            host=self.options.host,
            port=self.options.port,
            config_path=self.options.config_path,
            mitm_enabled=self.options.mitm_enabled,
            certs_dir=self.options.certs_dir,
            edit_timeout_s=self.options.edit_timeout_s,
            request_shutdown=self.request_shutdown,
            on_cache_toggle=self.close_active_tunnels,
            server_factory=self._server_factory,
        )
        self._server_thread = threading.Thread(
            target=self._runtime_graph.server.serve_forever, name="proxyscope-server"
        )

    def _configure_logging(self) -> None:
        root_logger = logging.getLogger()
        self._previous_root_handlers = list(root_logger.handlers)
        self._previous_root_level = root_logger.level
        assert self._runtime_graph is not None
        configure_logging(level=self._runtime_graph.settings.log_level)
        self._logging_configured = True

    def _wait_for_shutdown(self) -> None:
        while self.server_thread.is_alive() and not self._shutdown_event.wait(timeout=0.2):
            pass

    def _stop_accepting_requests(self) -> None:
        with self._server_shutdown_lock:
            if self._server_shutdown_requested:
                return
            self._server_shutdown_requested = True
        server = None if self._runtime_graph is None else self._runtime_graph.server
        thread = self._server_thread
        if server is not None and thread is not None and thread.is_alive():
            server.shutdown()

    def _restore_logging(self) -> None:
        if not self._logging_configured:
            return
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
        for handler in self._previous_root_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(self._previous_root_level)
        self._logging_configured = False
