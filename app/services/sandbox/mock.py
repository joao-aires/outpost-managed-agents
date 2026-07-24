import logging
import base64
import uuid
from typing import Dict, Any
from app.services.sandbox.base import BaseSandboxDriver

logger = logging.getLogger("outpost_cma.sandbox.mock")

class LocalMockDriver(BaseSandboxDriver):
    """
    Mock driver for local development and unit testing without a Kubernetes cluster.
    """
    def __init__(self):
        self.sandboxes: Dict[str, Dict[str, Any]] = {}

    async def initialize(self) -> None:
        logger.info("Initializing Local Mock Sandbox Driver...")

    async def create_sandbox(self, session_id: str) -> str:
        sandbox_id = f"mock-sandbox-{session_id[:8]}-{uuid.uuid4().hex[:6]}"
        self.sandboxes[sandbox_id] = {
            "session_id": session_id,
            "files": {},
            "commands": []
        }
        logger.info(f"[MOCK] Created sandbox environment: {sandbox_id}")
        return sandbox_id

    async def execute_command(self, sandbox_id: str, command: str) -> Dict[str, str]:
        logger.info(f"[MOCK CMD] Running on {sandbox_id}: {command}")
        if sandbox_id in self.sandboxes:
            self.sandboxes[sandbox_id]["commands"].append(command)
        
        cmd_cleaned = command.strip()
        if cmd_cleaned == "pwd":
            return {"stdout": "/workspace\n", "stderr": "", "exit_code": "0"}
        elif cmd_cleaned == "whoami":
            return {"stdout": "agent\n", "stderr": "", "exit_code": "0"}
        elif cmd_cleaned.startswith("echo"):
            parts = cmd_cleaned.split("echo ", 1)
            msg = parts[1].replace('"', '').replace("'", "") if len(parts) > 1 else ""
            return {"stdout": f"{msg}\n", "stderr": "", "exit_code": "0"}
            
        return {"stdout": f"Mock run output for: {command}\n", "stderr": "", "exit_code": "0"}

    async def read_file(self, sandbox_id: str, path: str) -> bytes:
        logger.info(f"[MOCK FILE] Reading {path} from {sandbox_id}")
        if sandbox_id in self.sandboxes and path in self.sandboxes[sandbox_id]["files"]:
            return self.sandboxes[sandbox_id]["files"][path]
        return b"Mock file content placeholder."

    async def write_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        logger.info(f"[MOCK FILE] Writing {len(content)} bytes to {path} on {sandbox_id}")
        if sandbox_id in self.sandboxes:
            self.sandboxes[sandbox_id]["files"][path] = content
        return True

    async def delete_sandbox(self, sandbox_id: str) -> None:
        logger.info(f"[MOCK] Destroyed sandbox: {sandbox_id}")
        if sandbox_id in self.sandboxes:
            del self.sandboxes[sandbox_id]

    async def reconcile_warm_pool(self) -> None:
        pass
