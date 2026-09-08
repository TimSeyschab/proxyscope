import logging
from unittest.mock import Mock, patch

import pytest

from proxyscope.application.configuration import ConfigDocument, JsonConfigRepository, RuntimeSettings
from tests.application.commands.handlers._helpers import config_handler
from tests.support.runtime_context import RuntimeTestContext


@pytest.mark.parametrize("arguments", [["config"], ["config", "SHOW"]])
@pytest.mark.parametrize("attached", [False, True])
def test_show_reports_attached_path(tmp_path, arguments, attached):
    path = tmp_path / "runtime.json" if attached else None
    config = RuntimeTestContext(config_path=path)
    result = config_handler(config).execute(arguments, on_cache_toggle=None)
    assert result.handled
    assert result.status_message == f"Config path: {path if attached else '<not attached>'}"


def test_save_requires_path_and_unknown_action_returns_usage():
    handler = config_handler(RuntimeTestContext())
    assert handler.execute(["config", "save"], on_cache_toggle=None).status_message.startswith("Usage: config save")
    assert (
        handler.execute(["config", "unknown"], on_cache_toggle=None).status_message
        == "Usage: config [show|save [path]|reload]"
    )


@pytest.mark.parametrize("explicit_path", [False, True])
def test_save_persists_settings_and_attaches_path(tmp_path, explicit_path):
    path = tmp_path / "config with spaces.json"
    config = RuntimeTestContext(config_path=None if explicit_path else path, log_level=logging.DEBUG)
    arguments = ["config", "save", *str(path).split(" ")] if explicit_path else ["config", "save"]
    result = config_handler(config).execute(arguments, on_cache_toggle=None)
    assert result.status_message == f"Config saved: {path}"
    assert config.config_path == path
    assert JsonConfigRepository().load(path).settings.log_level == logging.DEBUG


@pytest.mark.parametrize("action", ["save", "reload"])
@pytest.mark.parametrize("error", [OSError("disk unavailable"), ValueError("invalid document")])
def test_repository_failures_are_reported_without_notifying_cache(tmp_path, action, error):
    repository = Mock(spec=JsonConfigRepository)
    repository.save.side_effect = error
    repository.load.side_effect = error
    config = RuntimeTestContext(config_path=tmp_path / "config.json", config_repository=repository)
    before = config.settings
    callback = Mock()
    result = config_handler(config).execute(["config", action], on_cache_toggle=callback)
    assert result.status_message == f"Config {action} failed: {error}"
    assert result.updated_log_level is None
    assert config.settings == before
    callback.assert_not_called()


def test_reload_without_attached_path_preserves_settings():
    config = RuntimeTestContext()
    callback = Mock()
    result = config_handler(config).execute(["config", "reload"], on_cache_toggle=callback)
    assert result.status_message == "No attached config path. Use: config save <path>"
    callback.assert_not_called()


@pytest.mark.parametrize("cache_changed", [False, True])
@pytest.mark.parametrize("has_callback", [False, True])
def test_reload_applies_settings_and_notifies_only_for_cache_change(tmp_path, cache_changed, has_callback):
    path = tmp_path / "config.json"
    config = RuntimeTestContext(config_path=path)
    JsonConfigRepository().save(
        path,
        ConfigDocument(
            settings=RuntimeSettings.create(log_level=logging.DEBUG, cache_invalidation_enabled=not cache_changed)
        ),
    )
    callback = Mock() if has_callback else None
    with patch.object(config.configuration.repository, "save") as save:
        result = config_handler(config).execute(["config", "reload"], on_cache_toggle=callback)
        save.assert_not_called()
    assert result.status_message == f"Config reloaded: {path}"
    assert result.updated_log_level == config.log_level == logging.DEBUG
    assert config.cache_invalidation_enabled is not cache_changed
    if callback is not None:
        assert callback.call_count == int(cache_changed)
