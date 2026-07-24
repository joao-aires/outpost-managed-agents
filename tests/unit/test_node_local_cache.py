import pytest
from app.config import settings
from app.services.sandbox.direct import DirectPodDriver

def test_build_pod_manifest_with_node_local_cache():
    settings.ENABLE_NODE_LOCAL_CACHE = True
    settings.NODE_CACHE_HOST_PATH = "/var/lib/outpost/cache"
    settings.NODE_CACHE_MOUNT_PATH = "/opt/outpost-cache"

    driver = DirectPodDriver()
    manifest = driver._build_pod_manifest("test-pod", {"app": "test"})

    # Verify Volume Mounts
    container = manifest.spec.containers[0]
    mount_names = [m.name for m in container.volume_mounts]
    assert "node-tool-cache" in mount_names

    target_mount = next(m for m in container.volume_mounts if m.name == "node-tool-cache")
    assert target_mount.mount_path == "/opt/outpost-cache"
    assert target_mount.read_only is True

    # Verify HostPath Volumes
    vol_names = [v.name for v in manifest.spec.volumes]
    assert "node-tool-cache" in vol_names
    target_vol = next(v for v in manifest.spec.volumes if v.name == "node-tool-cache")
    assert target_vol.host_path.path == "/var/lib/outpost/cache"

    # Verify Environment Variable Path
    path_env = next(e for e in container.env if e.name == "PATH")
    assert "/opt/outpost-cache/bin" in path_env.value
