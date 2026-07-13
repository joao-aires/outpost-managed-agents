import abc
from typing import Dict, Any

class BaseSandboxDriver(abc.ABC):
    """
    Abstract Base Class defining the contract for sandbox execution engines.
    """
    
    @abc.abstractmethod
    async def initialize(self) -> None:
        """Initializes API clients and validates cluster availability."""
        pass

    @abc.abstractmethod
    async def create_sandbox(self, session_id: str) -> str:
        """Provisions a sandbox container/pod and returns the active identifier (pod name)."""
        pass

    @abc.abstractmethod
    async def execute_command(self, sandbox_id: str, command: str) -> Dict[str, str]:
        """Executes a bash command inside the sandbox container and returns stdout, stderr, and exit_code."""
        pass

    @abc.abstractmethod
    async def read_file(self, sandbox_id: str, path: str) -> bytes:
        """Reads a file from the sandbox workspace."""
        pass

    @abc.abstractmethod
    async def write_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        """Writes a file into the sandbox workspace."""
        pass

    @abc.abstractmethod
    async def delete_sandbox(self, sandbox_id: str) -> None:
        """Terminates the sandbox and frees underlying resources."""
        pass

    @abc.abstractmethod
    async def reconcile_warm_pool(self) -> None:
        """Triggered periodically in the background to handle pool reconciliation."""
        pass
