import json
from typing import Dict, List, Any, Optional
from app.services.harness.base import BaseHarnessDriver

class ClaudeCodeHarnessDriver(BaseHarnessDriver):
    """
    Driver for Anthropic Claude Code / Ant CLI coding agent harness.
    """
    
    @property
    def harness_name(self) -> str:
        return "claude-code"

    def get_init_script(self, agent_config: Dict[str, Any], environment: Dict[str, Any]) -> Optional[str]:
        custom_init = environment.get("init_script", "")
        script = """#!/bin/bash
set -e
echo "[Outpost Harness] Initializing Claude Code agent harness..."
mkdir -p /home/agent/.claude /workspace/.skills /workspace/.tools
if ! command -v ant &> /dev/null && ! command -v claude &> /dev/null; then
    echo "[Outpost Harness] Installing Claude Code CLI..."
    npm install -g @anthropic-ai/claude-code || true
fi
"""
        if custom_init:
            script += f"\n# Custom environment init script\n{custom_init}\n"
            
        script += "\necho '[Outpost Harness] Claude Code harness setup complete.'\n"
        return script

    def get_config_files(self, agent_config: Dict[str, Any], system_prompt: Optional[str]) -> Dict[str, str]:
        claude_json = {
            "autoApprove": agent_config.get("auto_approve", True),
            "customSystemPrompt": system_prompt or "You are an autonomous coding assistant executing in a secure Kubernetes sandbox.",
            "allowedTools": agent_config.get("allowed_tools", ["bash", "write_file", "read_file", "git"]),
            "telemetry": agent_config.get("telemetry", False)
        }
        
        # Merge user custom config files if provided
        config_files = {
            "/home/agent/.claude/config.json": json.dumps(claude_json, indent=2)
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
        # Ensure standard Claude tool schemas (bash, write_file, read_file)
        names = {t.get("name") for t in tools if isinstance(t, dict)}
        prepared = list(tools)
        
        if "bash" not in names:
            prepared.append({
                "name": "bash",
                "description": "Execute shell commands inside the Kubernetes sandbox environment.",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"]
                }
            })
        if "write_file" not in names:
            prepared.append({
                "name": "write_file",
                "description": "Create or overwrite a file in the sandbox environment.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["path", "content"]
                }
            })
        if "read_file" not in names:
            prepared.append({
                "name": "read_file",
                "description": "Read file contents from the sandbox environment.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"]
                }
            })
        return prepared
