from proxyscope.application.configuration import RuntimeConfigurationService
from proxyscope.application.runtime_settings import RuntimeSettingsState


class SettingsApplicationService:
    def __init__(self, settings: RuntimeSettingsState, configuration: RuntimeConfigurationService) -> None:
        self._settings = settings
        self._configuration = configuration

    def add_whitelist_entry(self, value: str) -> str:
        added = self._settings.add_whitelist_entry(value)
        self._configuration.save()
        return f"Added selected site to whitelist: {added}"

    def remove_whitelist_entry(self, value: str) -> str:
        removed = self._settings.remove_whitelist_entry(value)
        if removed:
            self._configuration.save()
            return f"Removed selected site from whitelist: {value}"
        return f"Selected site not in whitelist: {value}"
