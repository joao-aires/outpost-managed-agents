import json
from typing import Dict, List, Any, Optional
from app.services.harness.base import BaseHarnessDriver

class CustomHarnessDriver(BaseHarnessDriver):
    """
    Driver for Custom coding agent harnesses executing user-defined initialization scripts and configs.
    """
    
    @property
    def harness_name(self) -> str:
        return "custom"

    def get_init_script(self, agent_config: Dict[str, Any], environment: Dict[str, Any]) -> Optional[str]:
        custom_init = environment.get("init_script", "")
        script = """#!/bin/bash
set -e
echo "[Outpost Harness] Initializing Custom Agent Harness..."
mkdir -p /workspace/.skills /workspace/.tools
"""
        if custom_init:
            script += f"\n# Custom User Initialization Script\n{custom_init}\n"
            
        script += "\necho '[Outpost Harness] Custom harness setup complete.'\n"
        return script

    def get_config_files(self, agent_config: Dict[str, Any], system_prompt: Optional[str]) -> Dict[str, str]:
        config_files = {}
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
