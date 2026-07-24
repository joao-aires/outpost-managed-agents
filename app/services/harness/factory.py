from typing import Dict
from app.services.harness.base import BaseHarnessDriver
from app.services.harness.claude_code import ClaudeCodeHarnessDriver
from app.services.harness.opencode import OpenCodeHarnessDriver
from app.services.harness.aider import AiderHarnessDriver
from app.services.harness.cursor import CursorHarnessDriver
from app.services.harness.custom import CustomHarnessDriver

class HarnessDriverFactory:
    """
    Factory to retrieve harness drivers based on the agent harness type string.
    """
    _drivers: Dict[str, BaseHarnessDriver] = {
        "claude-code": ClaudeCodeHarnessDriver(),
        "opencode": OpenCodeHarnessDriver(),
        "aider": AiderHarnessDriver(),
        "cursor": CursorHarnessDriver(),
        "custom": CustomHarnessDriver(),
    }

    @classmethod
    def get_driver(cls, harness_name: str) -> BaseHarnessDriver:
        driver = cls._drivers.get((harness_name or "claude-code").lower())
        if not driver:
            # Fallback to custom driver if unrecognized harness string
            return cls._drivers["custom"]
        return driver

    @classmethod
    def register_driver(cls, name: str, driver: BaseHarnessDriver) -> None:
        cls._drivers[name.lower()] = driver
