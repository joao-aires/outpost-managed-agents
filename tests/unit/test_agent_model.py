import pytest
from app.models.agent import Agent

def test_agent_model_defaults():
    agent = Agent(name="Default Harness Agent")
    data = agent.to_dict()
    assert data["name"] == "Default Harness Agent"
    assert data["model"] == "claude-3-5-sonnet-latest"
    assert data["harness"] == "claude-code"
    assert data["skills"] == []
    assert data["tools"] == []
    assert data["environment"] == {}
    assert data["agent_config"] == {}

def test_agent_model_custom_harness():
    agent = Agent(
        name="OpenCode Custom Agent",
        model="qwen2.5-coder",
        harness="opencode",
        system="Custom system prompt",
        skills=[{"name": "test-skill", "content": "Skill description"}],
        environment={"init_script": "echo 'hello'", "env_vars": {"KEY": "VAL"}},
        agent_config={"auto_execute": True}
    )
    data = agent.to_dict()
    assert data["harness"] == "opencode"
    assert data["model"] == "qwen2.5-coder"
    assert len(data["skills"]) == 1
    assert data["environment"]["env_vars"]["KEY"] == "VAL"
    assert data["agent_config"]["auto_execute"] is True
