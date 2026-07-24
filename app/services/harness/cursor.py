import json
from typing import Dict, List, Any, Optional
from app.services.harness.base import BaseHarnessDriver

class CursorHarnessDriver(BaseHarnessDriver):
    """
    Driver for Cursor Agent coding harness.
    """
    
    @property
    def harness_name(self) -> str:
        return "cursor"

    def get_init_script(self, agent_config: Dict[str, Any], environment: Dict[str, Any]) -> Optional[str]:
        custom_init = environment.get("init_script", "")
        script = """#!/bin/bash
set -e
echo "[Outpost Harness] Initializing Cursor Agent harness..."
mkdir -p /home/agent/.cursor /workspace/.skills /workspace/.tools
"""
        if custom_init:
            script += f"\n# Custom environment init script\n{custom_init}\n"
            
        script += "\necho '[Outpost Harness] Cursor Agent harness setup complete.'\n"
        return script

    def get_config_files(self, agent_config: Dict[str, Any], system_prompt: Optional[str]) -> Dict[str, str]:
        cursor_json = {
            "agent_mode": agent_config.get("agent_mode", "autonomous"),
            "system_prompt": system_prompt or "You are a Cursor Coding Agent executing in an Outpost Kubernetes Sandbox."
        }
        
        config_files = {
            "/home/agent/.cursor/agent.json": json.dumps(cursor_json, indent=2)
        }
        
        extra_files = agent_config.get("config_files", {})
        if isinstance(extra_files, dict):
            for path, content in extra_files.items():
                if isinstance(content, dict):
                    config_files[path] = json.dumps(content, indent=2)
                else:
                    config_files[path] = str(content)
                    
        return config_files

    def prepare_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return list(tools)
