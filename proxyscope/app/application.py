import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from proxyscope.adapters.factory import create_default_runtime_application_services
from proxyscope.adapters.observability.events import RuntimeEventDispatcher
from proxyscope.adapters.observability.logging import configure_logging
from proxyscope.app.composition import create_proxy_runtime_context
from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.journal import RequestJournal
from proxyscope.application.policy_administration import PolicyAdministrationService
from proxyscope.application.response_edits import ResponseModifierService
from proxyscope.application.runtime_settings import RuntimeSettingsState
from proxyscope.application.services import RuntimeApplicationServices
from proxyscope.config.repository import JsonConfigRepository
from proxyscope.proxy.server import ProxyHTTPServer, create_server

LOGGER = logging.getLogger("pscope.app")


@dataclass(frozen=True)
class ApplicationOptions:
    host: str = "127.0.0.1"
    port: int = 8080
    config_path: str | Path | None = None
    mitm_enabled: bool | None = None
    certs_dir: str | Path | None = None
    use_ui: bool = False
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
        self._settings: RuntimeSettingsState | None = None
        self._policies: PolicyAdministrationService | None = None
        self._configuration: RuntimeConfigurationService | None = None
        self._request_journal: RequestJournal | None = None
        self._response_modifier: ResponseModifierService | None = None
        self._runtime_events: RuntimeEventDispatcher | None = None
        self._application_services: RuntimeApplicationServices | None = None
        self._server: ProxyHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._runtime_ui: logging.Handler | None = None
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
        if self._server is None:
            raise RuntimeError("Application has not been entered.")
        return self._server

    @property
    def response_modifier(self) -> ResponseModifierService:
        if self._response_modifier is None:
            raise RuntimeError("Application has not been entered.")
        return self._response_modifier

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
            self.response_modifier.set_interactive_enabled(self.options.use_ui)
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
            if self.options.use_ui:
                self._run_ui()
            else:
                self._wait_for_shutdown()
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
        server = self._server
        thread = self._server_thread
        self._stop_accepting_requests()
        if server is not None:
            server.close_all_active_tunnels()
        if self._response_modifier is not None:
            self._response_modifier.set_interactive_enabled(False)
            self._response_modifier.cancel_pending_edits()
        if server is not None:
            server.server_close()
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=self.options.thread_join_timeout_s)
        if self._runtime_events is not None:
            self._runtime_events.set_observer(None)
        self._restore_logging()

    def close_active_tunnels(self) -> None:
        closed = self.server.close_all_active_tunnels()
        LOGGER.info("Closed %d active SSL tunnel(s) after cache setting change.", closed)

    def _compose(self) -> None:
        repository = JsonConfigRepository()
        document = repository.load(Path(self.options.config_path)) if self.options.config_path else None
        settings = RuntimeSettingsState(settings=None if document is None else document.settings)
        policies = PolicyAdministrationService(rules=() if document is None else document.policies)
        configuration = RuntimeConfigurationService(
            settings=settings,
            policies=policies,
            repository=repository,
            path=self.options.config_path,
        )
        if self.options.mitm_enabled is not None:
            settings.set_mitm_enabled(self.options.mitm_enabled)
        if self.options.certs_dir is not None:
            settings.set_mitm_certs_dir(self.options.certs_dir)

        request_journal = RequestJournal()
        response_modifier = ResponseModifierService(edit_timeout_s=self.options.edit_timeout_s)
        runtime_events = RuntimeEventDispatcher()
        runtime_context = create_proxy_runtime_context(
            settings=settings,
            policies=policies,
            request_journal=request_journal,
            response_modifier=response_modifier,
            runtime_events=runtime_events,
        )
        services = create_default_runtime_application_services(
            settings=settings,
            policies=policies,
            configuration=configuration,
            request_journal=request_journal,
            response_modifier=response_modifier,
            proxy_base_url=f"http://{self.options.host}:{self.options.port}",
        )
        server = self._server_factory(
            self.options.host,
            self.options.port,
            runtime_context=runtime_context,
            auto_enable_mitm=settings.mitm_enabled,
            ca_root=settings.mitm_certs_dir,
        )
        self._settings = settings
        self._policies = policies
        self._configuration = configuration
        self._request_journal = request_journal
        self._response_modifier = response_modifier
        self._runtime_events = runtime_events
        self._application_services = services
        self._server = server
        self._server_thread = threading.Thread(target=server.serve_forever, name="proxyscope-server")

    def _configure_logging(self) -> None:
        root_logger = logging.getLogger()
        self._previous_root_handlers = list(root_logger.handlers)
        self._previous_root_level = root_logger.level
        assert self._settings is not None
        configure_logging(level=self._settings.log_level)
        self._logging_configured = True

    def _run_ui(self) -> None:
        from proxyscope.adapters.tui.cli import RuntimeCLI

        assert self._settings is not None
        assert self._policies is not None
        assert self._configuration is not None
        assert self._request_journal is not None
        assert self._response_modifier is not None
        assert self._runtime_events is not None
        runtime_ui = RuntimeCLI(
            settings=self._settings,
            policies=self._policies,
            configuration=self._configuration,
            request_journal=self._request_journal,
            response_modifier=self._response_modifier,
            proxy_base_url=f"http://{self.options.host}:{self.options.port}",
            application_services=self._application_services,
        )
        runtime_ui.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%H:%M:%S")
        )
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
        root_logger.addHandler(runtime_ui)
        root_logger.setLevel(self._settings.log_level)
        self._runtime_events.set_observer(runtime_ui)
        self._runtime_ui = runtime_ui
        runtime_ui.run(shutdown_server=self.request_shutdown, on_cache_toggle=self.close_active_tunnels)

    def _wait_for_shutdown(self) -> None:
        while self.server_thread.is_alive() and not self._shutdown_event.wait(timeout=0.2):
            pass

    def _stop_accepting_requests(self) -> None:
        with self._server_shutdown_lock:
            if self._server_shutdown_requested:
                return
            self._server_shutdown_requested = True
        server = self._server
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
