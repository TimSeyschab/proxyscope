from proxyscope.app.config.runtime import RuntimeConfig


class SettingsApplicationService:
    def __init__(self, runtime_config: RuntimeConfig) -> None:
        self._runtime_config = runtime_config

    def add_whitelist_entry(self, value: str) -> str:
        added = self._runtime_config.add_whitelist_entry(value)
        return f"Added selected site to whitelist: {added}"

    def remove_whitelist_entry(self, value: str) -> str:
        removed = self._runtime_config.remove_whitelist_entry(value)
        if removed:
            return f"Removed selected site from whitelist: {value}"
        return f"Selected site not in whitelist: {value}"
