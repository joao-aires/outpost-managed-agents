import pytest
from app.services.harness.aider import AiderHarnessDriver
from app.services.harness.cursor import CursorHarnessDriver
from app.services.harness.custom import CustomHarnessDriver

def test_aider_harness_driver():
    driver = AiderHarnessDriver()
    config_files = driver.get_config_files(system_prompt="Custom prompt", agent_config={"auto_commit": False})
    assert "/home/agent/.aider.conf.yml" in config_files
    assert "auto-commits:" in config_files["/home/agent/.aider.conf.yml"]

    init_script = driver.get_init_script(environment={"init_script": "echo 'Aider Ready'"}, agent_config={})
    assert "echo 'Aider Ready'" in init_script

def test_cursor_harness_driver():
    driver = CursorHarnessDriver()
    config_files = driver.get_config_files(system_prompt="Custom prompt", agent_config={"model": "cursor-fast"})
    assert "/home/agent/.cursor/agent.json" in config_files
    assert '"system_prompt": "Custom prompt"' in config_files["/home/agent/.cursor/agent.json"]

    init_script = driver.get_init_script(environment={}, agent_config={})
    assert "mkdir -p /home/agent/.cursor" in init_script

def test_custom_harness_driver():
    driver = CustomHarnessDriver()
    custom_configs = {".myconfig.json": '{"setting": true}'}
    config_files = driver.get_config_files(system_prompt="Custom prompt", agent_config={"config_files": custom_configs})
    assert ".myconfig.json" in config_files
    assert '{"setting": true}' in config_files[".myconfig.json"]

    init_script = driver.get_init_script(environment={"init_script": "python3 setup.py"}, agent_config={})
    assert "python3 setup.py" in init_script
