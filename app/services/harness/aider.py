import json
from typing import Dict, List, Any, Optional
from app.services.harness.base import BaseHarnessDriver

class AiderHarnessDriver(BaseHarnessDriver):
    """
    Driver for Aider Git-centric coding agent harness.
    """
    
    @property
    def harness_name(self) -> str:
        return "aider"

    def get_init_script(self, agent_config: Dict[str, Any], environment: Dict[str, Any]) -> Optional[str]:
        custom_init = environment.get("init_script", "")
        script = """#!/bin/bash
set -e
echo "[Outpost Harness] Initializing Aider Coding Agent harness..."
mkdir -p /home/agent/.aider /workspace/.skills /workspace/.tools
if ! command -v aider &> /dev/null; then
    echo "[Outpost Harness] Installing Aider Chat CLI..."
    pip install aider-chat || true
fi
git config --global user.email "agent@outpost.local" || true
git config --global user.name "Outpost Agent" || true
"""
        if custom_init:
            script += f"\n# Custom environment init script\n{custom_init}\n"
            
        script += "\necho '[Outpost Harness] Aider harness setup complete.'\n"
        return script

    def get_config_files(self, agent_config: Dict[str, Any], system_prompt: Optional[str]) -> Dict[str, str]:
        aider_yml = f"""# Aider Configuration
auto-commits: {str(agent_config.get("auto_commits", True)).lower()}
dirty-commits: true
model: {agent_config.get("model", "claude-3-5-sonnet-latest")}
"""
        config_files = {
            "/home/agent/.aider.conf.yml": aider_yml
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
