import json
from typing import Dict, List, Any, Optional
from app.services.harness.base import BaseHarnessDriver

class OpenCodeHarnessDriver(BaseHarnessDriver):
    """
    Driver for OpenCode Interpreter coding agent harness.
    """
    
    @property
    def harness_name(self) -> str:
        return "opencode"

    def get_init_script(self, agent_config: Dict[str, Any], environment: Dict[str, Any]) -> Optional[str]:
        custom_init = environment.get("init_script", "")
        script = """#!/bin/bash
set -e
echo "[Outpost Harness] Initializing OpenCode Interpreter agent harness..."
mkdir -p /home/agent/.opencode /workspace/.skills /workspace/.tools
if ! command -v opencode &> /dev/null; then
    echo "[Outpost Harness] Installing OpenCode Interpreter..."
    pip install opencode-interpreter || true
fi
"""
        if custom_init:
            script += f"\n# Custom environment init script\n{custom_init}\n"
            
        script += "\necho '[Outpost Harness] OpenCode harness setup complete.'\n"
        return script

    def get_config_files(self, agent_config: Dict[str, Any], system_prompt: Optional[str]) -> Dict[str, str]:
        opencode_json = {
            "interpreter": agent_config.get("interpreter", "python3"),
            "system_instruction": system_prompt or "You are an OpenCode Interpreter agent executing inside a secure sandbox.",
            "auto_execute": agent_config.get("auto_execute", True),
            "max_output_tokens": agent_config.get("max_output_tokens", 4096)
        }
        
        config_files = {
            "/home/agent/.opencode/opencode.json": json.dumps(opencode_json, indent=2)
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
