import logging
from app.config import settings
from app.services.sandbox.base import BaseSandboxDriver
from app.services.sandbox.direct import DirectPodDriver
from app.services.sandbox.sigs import SigsSandboxDriver
from app.services.sandbox.mock import LocalMockDriver

logger = logging.getLogger("outpost_cma.sandbox.factory")

class SandboxDriverFactory:
    _instance: BaseSandboxDriver = None
    _active_driver_type: str = None

    @classmethod
    def get_driver(cls) -> BaseSandboxDriver:
        driver_type = getattr(settings, "SANDBOX_DRIVER", "direct").lower()
        
        if cls._instance is not None and cls._active_driver_type == driver_type:
            return cls._instance

        logger.info(f"Loading Sandbox Execution Driver: {driver_type}")
        cls._active_driver_type = driver_type
        
        if driver_type == "direct":
            cls._instance = DirectPodDriver()
        elif driver_type in ("sigs-sandbox", "sigs"):
            cls._instance = SigsSandboxDriver()
        elif driver_type == "mock":
            cls._instance = LocalMockDriver()
        else:
            logger.warning(f"Unknown driver type '{driver_type}'. Defaulting to LocalMockDriver.")
            cls._instance = LocalMockDriver()

        return cls._instance

class SandboxDriverProxy(BaseSandboxDriver):
    """
    Proxy wrapper that dynamically delegates calls to the active sandbox driver.
    """
    async def initialize(self) -> None:
        await SandboxDriverFactory.get_driver().initialize()

    async def create_sandbox(self, session_id: str) -> str:
        return await SandboxDriverFactory.get_driver().create_sandbox(session_id)

    async def execute_command(self, sandbox_id: str, command: str) -> dict:
        return await SandboxDriverFactory.get_driver().execute_command(sandbox_id, command)

    async def read_file(self, sandbox_id: str, path: str) -> bytes:
        return await SandboxDriverFactory.get_driver().read_file(sandbox_id, path)

    async def write_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        return await SandboxDriverFactory.get_driver().write_file(sandbox_id, path, content)

    async def delete_sandbox(self, sandbox_id: str) -> None:
        await SandboxDriverFactory.get_driver().delete_sandbox(sandbox_id)

    async def reconcile_warm_pool(self) -> None:
        await SandboxDriverFactory.get_driver().reconcile_warm_pool()

# Global dynamic driver proxy
sandbox_driver = SandboxDriverProxy()
