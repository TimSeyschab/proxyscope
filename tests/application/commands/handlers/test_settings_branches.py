from unittest.mock import Mock, patch

import pytest

from tests.application.commands.handlers._helpers import settings_handler
from tests.support.runtime_context import RuntimeTestContext


@pytest.mark.parametrize(
    ("parts", "message"),
    [
        (["whitelist", "add"], "Usage: whitelist add"),
        (["whitelist", "remove"], "Usage: whitelist remove"),
        (["whitelist", "unknown"], "Usage: whitelist"),
        (["cache", "unknown"], "Usage: cache"),
        (["mitm", "unknown"], "Usage: mitm"),
        (["mitm", "certs-dir"], "Usage: mitm certs-dir"),
        (["loglevel", "invalid"], "Unsupported log level"),
        (["whitelist", "add", "http://"], "Invalid whitelist entry"),
        (["whitelist", "remove", "http://"], "Invalid whitelist entry"),
    ],
)
def test_invalid_settings_commands_leave_state_unchanged(parts, message):
    config = RuntimeTestContext()
    before = config.settings
    with patch.object(config.configuration, "save") as save:
        result = settings_handler(config).execute(parts, on_cache_toggle=None)
        assert result.handled
        assert result.status_message.startswith(message)
        save.assert_not_called()
    assert config.settings == before


@pytest.mark.parametrize("initial", [False, True])
@pytest.mark.parametrize("action", ["on", "off", "toggle"])
@pytest.mark.parametrize("has_callback", [False, True])
def test_cache_actions_update_state_and_persist(initial, action, has_callback):
    config = RuntimeTestContext(cache_invalidation_enabled=initial)
    callback = Mock() if has_callback else None
    with patch.object(config.configuration, "save") as save:
        result = settings_handler(config).execute(["cache", action], on_cache_toggle=callback)
        save.assert_called_once_with()
    expected = not initial if action == "toggle" else action == "on"
    assert config.cache_invalidation_enabled is expected
    assert result.status_message == f"Cache invalidation {'enabled' if expected else 'disabled'}."
    if callback is not None:
        callback.assert_called_once_with()


@pytest.mark.parametrize("command", ["cache", "mitm"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("suffix", [[], ["show"]])
def test_show_reports_current_boolean_state(command, enabled, suffix):
    config = RuntimeTestContext(cache_invalidation_enabled=enabled, mitm_enabled=enabled)
    result = settings_handler(config).execute([command, *suffix], on_cache_toggle=None)
    assert (": on" if enabled else ": off") in result.status_message


def test_whitelist_show_clear_and_missing_remove():
    config = RuntimeTestContext(log_whitelist=["api.test"])
    handler = settings_handler(config)
    assert handler.execute(["wl"], on_cache_toggle=None).status_message == "Whitelist: api.test"
    assert (
        handler.execute(["wl", "remove", "missing.test"], on_cache_toggle=None).status_message
        == "Not in whitelist: missing.test"
    )
    assert handler.execute(["wl", "clear"], on_cache_toggle=None).status_message.startswith("Whitelist cleared")
    assert config.whitelist_entries() == ()
    assert not handler.execute(["unknown"], on_cache_toggle=None).handled


def test_mitm_on_restores_disabled_state():
    config = RuntimeTestContext(mitm_enabled=False)
    assert (
        settings_handler(config).execute(["mitm", "on"], on_cache_toggle=None).status_message.startswith("MITM enabled")
    )
    assert config.mitm_enabled
