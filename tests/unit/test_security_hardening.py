import pytest
from app.services.sandbox.direct import DirectPodDriver
from app.config import settings

def test_sandbox_pod_manifest_security_hardening():
    """
    Verifies that DirectPodDriver generates sandbox pod manifests with ADR 0002 security hardening settings.
    """
    driver = DirectPodDriver()
    pod = driver._build_pod_manifest("test-sec-pod", {"app": "test"})
    
    container = pod.spec.containers[0]
    sec_ctx = container.security_context
    
    # 1. Non-root user enforcement
    assert sec_ctx.run_as_non_root is True
    assert sec_ctx.run_as_user == 1000
    assert sec_ctx.run_as_group == 1000
    assert sec_ctx.allow_privilege_escalation is False
    
    # 2. Read-only root filesystem
    assert sec_ctx.read_only_root_filesystem is True
    
    # 3. Drop all Linux capabilities
    assert sec_ctx.capabilities.drop == ["ALL"]
    
    # 4. Default seccomp profile
    assert sec_ctx.seccomp_profile.type == "RuntimeDefault"
    
    # 5. Writable emptyDir volumes for /workspace and /tmp
    mount_paths = [m.mount_path for m in container.volume_mounts]
    assert "/workspace" in mount_paths
    assert "/tmp" in mount_paths

def test_sandbox_pod_manifest_custom_runtime_class(monkeypatch):
    """
    Verifies that sandbox pods apply custom runtimeClassName (e.g. gvisor) when configured.
    """
    monkeypatch.setattr(settings, "SANDBOX_RUNTIME_CLASS", "gvisor")
    driver = DirectPodDriver()
    pod = driver._build_pod_manifest("test-gvisor-pod", {"app": "test"})
    
    assert pod.spec.runtime_class_name == "gvisor"
