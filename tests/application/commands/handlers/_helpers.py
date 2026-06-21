from proxyscope.application.commands.handlers.config import ConfigCommandHandler
from proxyscope.application.commands.handlers.policy import PolicyCommandHandler
from proxyscope.application.commands.handlers.settings import SettingsCommandHandler
from tests.support.runtime_context import RuntimeTestContext, runtime_dependencies


def settings_handler(config: RuntimeTestContext) -> SettingsCommandHandler:
    dependencies = runtime_dependencies(config)
    return SettingsCommandHandler(
        settings=dependencies["settings"],
        configuration=dependencies["configuration"],
    )


def policy_handler(config: RuntimeTestContext) -> PolicyCommandHandler:
    dependencies = runtime_dependencies(config)
    return PolicyCommandHandler(
        policies=dependencies["policies"],
        configuration=dependencies["configuration"],
    )


def config_handler(config: RuntimeTestContext) -> ConfigCommandHandler:
    dependencies = runtime_dependencies(config)
    return ConfigCommandHandler(
        settings=dependencies["settings"],
        configuration=dependencies["configuration"],
    )
