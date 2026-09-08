from unittest.mock import Mock

from proxyscope.application.settings import SettingsApplicationService
from tests.support.runtime_context import RuntimeTestContext


def test_whitelist_mutations_persist_only_when_needed():
    config = RuntimeTestContext()
    configuration = Mock()
    service = SettingsApplicationService(config.settings_state, configuration)
    assert service.add_whitelist_entry("https://API.TEST/items") == "Added selected site to whitelist: api.test"
    assert config.whitelist_entries() == ("api.test",)
    assert configuration.save.call_count == 1
    assert service.remove_whitelist_entry("missing.test") == "Selected site not in whitelist: missing.test"
    assert configuration.save.call_count == 1
    assert service.remove_whitelist_entry("api.test") == "Removed selected site from whitelist: api.test"
    assert config.whitelist_entries() == ()
    assert configuration.save.call_count == 2
