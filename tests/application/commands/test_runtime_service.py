from unittest.mock import Mock

import pytest

from proxyscope.application.commands.runtime_service import RuntimeCommandService
from tests.support.runtime_context import RuntimeTestContext


@pytest.fixture
def runtime_commands():
    config = RuntimeTestContext()
    return config, RuntimeCommandService(settings=config.settings_state, configuration=config.configuration)


@pytest.mark.parametrize("command", ["", "  ", "unknown", "unknown argument"])
def test_unknown_or_empty_command_is_unhandled(runtime_commands, command):
    _, service = runtime_commands
    assert not service.execute(command, on_cache_toggle=None).handled
    assert not service.execute_parts([], on_cache_toggle=None).handled


def test_malformed_quotes_report_syntax_error(runtime_commands):
    config, service = runtime_commands
    before = config.settings
    result = service.execute('mitm certs-dir "unterminated', on_cache_toggle=None)
    assert result.handled
    assert result.status_message.startswith("Invalid command syntax:")
    assert config.settings == before


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("LOGLEVEL", "Current log level: INFO"),
        ("whitelist show", "Whitelist is empty"),
        ("wl", "Whitelist is empty"),
        ("cache", "Cache invalidation: on"),
        ("mitm show", "MITM: on"),
        ("config show", "Config path: <not attached>"),
    ],
)
def test_routes_commands_to_correct_handler(runtime_commands, command, message):
    _, service = runtime_commands
    result = service.execute(command, on_cache_toggle=None)
    assert result.handled
    assert result.status_message.startswith(message)


def test_quoted_path_and_cache_callback_reach_handlers(runtime_commands):
    config, service = runtime_commands
    service.execute('mitm certs-dir "directory with spaces"', on_cache_toggle=None)
    assert str(config.mitm_certs_dir) == "directory with spaces"
    callback = Mock()
    service.execute("cache off", on_cache_toggle=callback)
    callback.assert_called_once_with()
    assert not config.cache_invalidation_enabled
