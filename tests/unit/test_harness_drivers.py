import pytest
import json
from app.services.harness.factory import HarnessDriverFactory
from app.services.harness.claude_code import ClaudeCodeHarnessDriver
from app.services.harness.opencode import OpenCodeHarnessDriver
from app.services.harness.aider import AiderHarnessDriver
from app.services.harness.cursor import CursorHarnessDriver
from app.services.harness.custom import CustomHarnessDriver

def test_harness_factory_resolution():
    assert isinstance(HarnessDriverFactory.get_driver("claude-code"), ClaudeCodeHarnessDriver)
    assert isinstance(HarnessDriverFactory.get_driver("opencode"), OpenCodeHarnessDriver)
    assert isinstance(HarnessDriverFactory.get_driver("aider"), AiderHarnessDriver)
    assert isinstance(HarnessDriverFactory.get_driver("cursor"), CursorHarnessDriver)
    assert isinstance(HarnessDriverFactory.get_driver("custom"), CustomHarnessDriver)
    assert isinstance(HarnessDriverFactory.get_driver("unknown-harness"), CustomHarnessDriver)

def test_claude_code_harness_driver():
    driver = HarnessDriverFactory.get_driver("claude-code")
    agent_config = {"auto_approve": True, "allowed_tools": ["bash"]}
    env = {"init_script": "echo 'custom setup'"}
    
    init_script = driver.get_init_script(agent_config, env)
    assert "Initializing Claude Code agent harness" in init_script
    assert "custom setup" in init_script
    
    config_files = driver.get_config_files(agent_config, "System prompt")
    assert "/home/agent/.claude/config.json" in config_files
    parsed_config = json.loads(config_files["/home/agent/.claude/config.json"])
    assert parsed_config["autoApprove"] is True
    assert parsed_config["customSystemPrompt"] == "System prompt"

def test_opencode_harness_driver():
    driver = HarnessDriverFactory.get_driver("opencode")
    agent_config = {"interpreter": "python3"}
    config_files = driver.get_config_files(agent_config, "OpenCode prompt")
    assert "/home/agent/.opencode/opencode.json" in config_files
    parsed = json.loads(config_files["/home/agent/.opencode/opencode.json"])
    assert parsed["interpreter"] == "python3"

def test_skills_preparation():
    driver = HarnessDriverFactory.get_driver("claude-code")
    skills = [{"name": "db-migrate", "content": "Run alembic upgrade head"}]
    skill_files = driver.prepare_skills(skills)
    assert "/workspace/.skills/db-migrate/SKILL.md" in skill_files
    assert skill_files["/workspace/.skills/db-migrate/SKILL.md"] == "Run alembic upgrade head"
