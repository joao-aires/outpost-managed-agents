from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

class BaseHarnessDriver(ABC):
    """
    Abstract Base Class for Coding Agent Harness Drivers (Claude Code, OpenCode, Aider, Cursor, Custom).
    """
    
    @property
    @abstractmethod
    def harness_name(self) -> str:
        """Returns the identifier name of the harness."""
        pass

    @abstractmethod
    def get_init_script(self, agent_config: Dict[str, Any], environment: Dict[str, Any]) -> Optional[str]:
        """
        Generates the bash initialization script to execute when bootstrapping the sandbox.
        """
        pass

    @abstractmethod
    def get_config_files(self, agent_config: Dict[str, Any], system_prompt: Optional[str]) -> Dict[str, str]:
        """
        Generates configuration files (e.g. .claude.json, opencode.json) to inject into the sandbox.
        Map of file path -> file content string.
        """
        pass

    @abstractmethod
    def prepare_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Formats or injects standard harness tools.
        """
        pass

    def prepare_skills(self, skills: List[Dict[str, Any]]) -> Dict[str, str]:
        """
        Maps skills list to filesystem files under /workspace/.skills/<skill_name>/SKILL.md
        """
        files = {}
        for skill in skills:
            if isinstance(skill, dict):
                name = skill.get("name", "custom-skill")
                content = skill.get("content") or skill.get("description", "")
                files[f"/workspace/.skills/{name}/SKILL.md"] = content
        return files
