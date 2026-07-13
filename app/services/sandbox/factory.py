import logging
from app.config import settings
from app.services.sandbox.base import BaseSandboxDriver
from app.services.sandbox.direct import DirectPodDriver
from app.services.sandbox.sigs import SigsSandboxDriver
from app.services.sandbox.mock import LocalMockDriver

logger = logging.getLogger("outpost_cma.sandbox.factory")

class SandboxDriverFactory:
    _instance: BaseSandboxDriver = None

    @classmethod
    def get_driver(cls) -> BaseSandboxDriver:
        if cls._instance is not None:
            return cls._instance

        # Load driver based on config setting
        driver_type = getattr(settings, "SANDBOX_DRIVER", "direct").lower()
        logger.info(f"Loading Sandbox Execution Driver: {driver_type}")
        
        if driver_type == "direct":
            cls._instance = DirectPodDriver()
        elif driver_type == "sigs-sandbox" or driver_type == "sigs":
            cls._instance = SigsSandboxDriver()
        elif driver_type == "mock":
            cls._instance = LocalMockDriver()
        else:
            logger.warning(f"Unknown driver type '{driver_type}'. Defaulting to LocalMockDriver.")
            cls._instance = LocalMockDriver()

        return cls._instance

# Global driver singleton
sandbox_driver = SandboxDriverFactory.get_driver()
